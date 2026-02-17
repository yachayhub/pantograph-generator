"""
Lightweight STEP (ISO 10303-21) parser for extracting 2D cutting profiles
from flat plate STEP files. Extracts lines and arcs from the bottom face (Z=0).
"""

import re
import math
from dataclasses import dataclass
from typing import Union, Optional, List, Tuple, Dict


@dataclass
class Point2D:
    x: float
    y: float

    def __eq__(self, other):
        if not isinstance(other, Point2D):
            return False
        return abs(self.x - other.x) < 0.001 and abs(self.y - other.y) < 0.001

    def distance_to(self, other: 'Point2D') -> float:
        return math.sqrt((self.x - other.x)**2 + (self.y - other.y)**2)


@dataclass
class LineSeg:
    start: Point2D
    end: Point2D


@dataclass
class ArcSeg:
    start: Point2D
    end: Point2D
    center: Point2D
    radius: float
    clockwise: bool  # True = G02, False = G03


Segment = Union[LineSeg, ArcSeg]


@dataclass
class Contour:
    segments: List[Segment]
    is_hole: bool = False

    @property
    def bounds(self) -> Tuple[float, float, float, float]:
        """Return (min_x, min_y, max_x, max_y)"""
        xs, ys = [], []
        for seg in self.segments:
            xs.extend([seg.start.x, seg.end.x])
            ys.extend([seg.start.y, seg.end.y])
            if isinstance(seg, ArcSeg):
                # Include arc extrema
                cx, cy, r = seg.center.x, seg.center.y, seg.radius
                for angle in [0, math.pi/2, math.pi, 3*math.pi/2]:
                    px = cx + r * math.cos(angle)
                    py = cy + r * math.sin(angle)
                    # Check if this extreme point is on the arc
                    a_start = math.atan2(seg.start.y - cy, seg.start.x - cx)
                    a_end = math.atan2(seg.end.y - cy, seg.end.x - cx)
                    if _angle_on_arc(angle, a_start, a_end, seg.clockwise):
                        xs.append(px)
                        ys.append(py)
        return (min(xs), min(ys), max(xs), max(ys))


def _angle_on_arc(angle: float, start: float, end: float, clockwise: bool) -> bool:
    """Check if angle is on arc sweep from start to end."""
    def normalize(a):
        while a < 0:
            a += 2 * math.pi
        while a >= 2 * math.pi:
            a -= 2 * math.pi
        return a

    angle = normalize(angle)
    start = normalize(start)
    end = normalize(end)

    if clockwise:  # CW = decreasing angle
        if start >= end:
            return end <= angle <= start
        else:
            return angle <= start or angle >= end
    else:  # CCW = increasing angle
        if end >= start:
            return start <= angle <= end
        else:
            return angle >= start or angle <= end


class StepParser:
    """Parse STEP files and extract 2D cutting contours."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.entities: Dict[int, Tuple[str, str]] = {}
        self._parse_file()

    def _parse_file(self):
        with open(self.filepath, 'r') as f:
            content = f.read()

        data_match = re.search(r'DATA;(.+?)ENDSEC;', content, re.DOTALL)
        if not data_match:
            raise ValueError("Invalid STEP file: no DATA section found")

        data = data_match.group(1)
        # Match entities: #NNN=...;  (may span multiple lines)
        entity_re = re.compile(r'(#\d+\s*=\s*.+?;)', re.DOTALL)
        for m in entity_re.finditer(data):
            raw = m.group(1).replace('\n', ' ').replace('\r', ' ')
            self._parse_entity(raw)

    def _parse_entity(self, raw: str):
        m = re.match(r'#(\d+)\s*=\s*(.+);', raw.strip())
        if not m:
            return
        eid = int(m.group(1))
        rest = m.group(2).strip()

        if rest.startswith('('):
            self.entities[eid] = ('COMPOUND', rest)
            return

        tm = re.match(r'([A-Z_0-9]+)\s*\((.*)\)$', rest, re.DOTALL)
        if tm:
            self.entities[eid] = (tm.group(1), tm.group(2))

    # --- Helper methods ---

    def _ref(self, s: str) -> Optional[int]:
        m = re.match(r'#(\d+)', s.strip())
        return int(m.group(1)) if m else None

    def _split_params(self, params_str: str) -> List[str]:
        parts, depth, cur = [], 0, ''
        for ch in params_str:
            if ch == '(':
                depth += 1; cur += ch
            elif ch == ')':
                depth -= 1; cur += ch
            elif ch == ',' and depth == 0:
                parts.append(cur.strip()); cur = ''
            else:
                cur += ch
        if cur.strip():
            parts.append(cur.strip())
        return parts

    def _get_coords(self, point_id: int) -> Tuple[float, float, float]:
        _, params = self.entities[point_id]
        parts = self._split_params(params)
        nums = re.findall(r'[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?', parts[1])
        return tuple(float(n) for n in nums)

    def _get_vertex_coords(self, vertex_id: int) -> Tuple[float, float, float]:
        _, params = self.entities[vertex_id]
        parts = self._split_params(params)
        return self._get_coords(self._ref(parts[1]))

    def _get_placement_origin(self, placement_id: int) -> Tuple[float, float, float]:
        _, params = self.entities[placement_id]
        parts = self._split_params(params)
        return self._get_coords(self._ref(parts[1]))

    def _get_placement_axis_z(self, placement_id: int) -> float:
        """Get the Z component of the axis direction."""
        _, params = self.entities[placement_id]
        parts = self._split_params(params)
        axis_ref = self._ref(parts[2])
        _, axis_params = self.entities[axis_ref]
        axis_parts = self._split_params(axis_params)
        nums = re.findall(r'[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?', axis_parts[1])
        return float(nums[2])

    def _get_circle_info(self, circle_id: int) -> Tuple[Tuple, float, int]:
        """Returns (center_3d, radius, placement_id)."""
        _, params = self.entities[circle_id]
        parts = self._split_params(params)
        placement_ref = self._ref(parts[1])
        radius = float(parts[2])
        center = self._get_placement_origin(placement_ref)
        return center, radius, placement_ref

    def _find_refs_in(self, s: str) -> List[int]:
        return [int(m.group(1)) for m in re.finditer(r'#(\d+)', s)]

    # --- Main extraction ---

    def extract_contours(self, face_id: Optional[int] = None) -> List[Contour]:
        """Extract 2D contours from a planar face.
        If face_id is given, use that face. Otherwise auto-detect the bottom face.
        """
        faces = self._get_all_advanced_faces()

        if face_id is None:
            face_id = self._find_best_planar_face(faces)

        if face_id is None:
            raise ValueError("No planar face found in STEP file")

        return self._extract_contours_from_face(faces, face_id)

    def _get_all_advanced_faces(self) -> dict:
        """Get all ADVANCED_FACE entities with bounds and surface refs."""
        faces = {}
        for eid, (etype, params) in self.entities.items():
            if etype == 'ADVANCED_FACE':
                parts = self._split_params(params)
                bound_refs = self._find_refs_in(parts[1])
                surface_ref = self._ref(parts[2])
                faces[eid] = {'bounds': bound_refs, 'surface': surface_ref}
        return faces

    def _find_best_planar_face(self, faces: dict) -> Optional[int]:
        """Find the bottom planar face (Z=0 or lowest Z, with most bounds)."""
        best_face = None
        best_z = float('inf')
        best_bound_count = 0
        z_tolerance = 0.01
        for fid, fdata in faces.items():
            stype, sparams = self.entities[fdata['surface']]
            if stype == 'PLANE':
                sp = self._split_params(sparams)
                placement_ref = self._ref(sp[1]) if len(sp) > 1 else self._ref(sp[0])
                origin = self._get_placement_origin(placement_ref)
                z = abs(origin[2])
                num_bounds = len(fdata['bounds'])
                if (z < best_z - z_tolerance) or \
                   (abs(z - best_z) < z_tolerance and num_bounds > best_bound_count):
                    best_z = z
                    best_face = fid
                    best_bound_count = num_bounds
        return best_face

    def _extract_contours_from_face(self, faces: dict, face_id: int) -> List[Contour]:
        """Extract 2D contours from a specific ADVANCED_FACE."""
        contours = []
        for bound_ref in faces[face_id]['bounds']:
            btype, bparams = self.entities[bound_ref]
            bparts = self._split_params(bparams)
            edge_loop_ref = self._ref(bparts[1])
            is_hole = (btype == 'FACE_BOUND')
            _, elparams = self.entities[edge_loop_ref]
            elparts = self._split_params(elparams)
            oe_refs = self._find_refs_in(elparts[1])
            segments = []
            for oe_ref in oe_refs:
                seg = self._process_oriented_edge(oe_ref)
                if seg:
                    segments.append(seg)
            if segments:
                contours.append(Contour(segments=segments, is_hole=is_hole))
        contours.sort(key=lambda c: (0 if c.is_hole else 1))
        return contours

    def extract_all_faces_3d(self) -> List[dict]:
        """Extract all faces with 3D edge data for 3D visualization.

        Returns a list of face info dicts:
        {
            'id': int,
            'surface_type': str ('PLANE' | 'CYLINDRICAL_SURFACE' | ...),
            'z_level': float or None (for PLANEs),
            'normal_z': float or None (for PLANEs, 1.0 = horizontal face),
            'num_bounds': int,
            'edges_3d': list of (xs, ys, zs) tuples (line segments as point lists),
            'is_cuttable': bool (True for horizontal PLANEs),
            'dimensions': (width, height) or None,
            'num_holes': int,
        }
        """
        faces = self._get_all_advanced_faces()
        result = []

        for fid, fdata in faces.items():
            stype, sparams = self.entities[fdata['surface']]
            z_level = None
            normal_z = None
            is_cuttable = False
            dimensions = None
            num_holes = 0

            if stype == 'PLANE':
                sp = self._split_params(sparams)
                placement_ref = self._ref(sp[1]) if len(sp) > 1 else self._ref(sp[0])
                origin = self._get_placement_origin(placement_ref)
                z_level = origin[2]
                try:
                    normal_z = self._get_placement_axis_z(placement_ref)
                except (KeyError, IndexError):
                    normal_z = 0.0
                # Cuttable = horizontal planar face (normal along Z axis)
                is_cuttable = abs(abs(normal_z) - 1.0) < 0.01 and len(fdata['bounds']) >= 1

                if is_cuttable:
                    # Count holes and get dimensions
                    for br in fdata['bounds']:
                        bt, _ = self.entities[br]
                        if bt == 'FACE_BOUND':
                            num_holes += 1
                    try:
                        contours = self._extract_contours_from_face(faces, fid)
                        for c in contours:
                            if not c.is_hole:
                                b = c.bounds
                                dimensions = (round(b[2] - b[0], 1), round(b[3] - b[1], 1))
                    except Exception:
                        pass

            # Extract 3D edges for wireframe
            edges_3d = self._extract_face_edges_3d(fdata['bounds'])

            result.append({
                'id': fid,
                'surface_type': stype,
                'z_level': z_level,
                'normal_z': normal_z,
                'num_bounds': len(fdata['bounds']),
                'edges_3d': edges_3d,
                'is_cuttable': is_cuttable,
                'dimensions': dimensions,
                'num_holes': num_holes,
            })

        return result

    def _extract_face_edges_3d(self, bound_refs: List[int]) -> List[tuple]:
        """Extract 3D edge segments as (xs, ys, zs) point lists."""
        edges = []
        for bref in bound_refs:
            btype, bparams = self.entities[bref]
            bparts = self._split_params(bparams)
            el_ref = self._ref(bparts[1])
            _, elparams = self.entities[el_ref]
            elparts = self._split_params(elparams)
            oe_refs = self._find_refs_in(elparts[1])

            for oe_ref in oe_refs:
                _, oe_params = self.entities[oe_ref]
                oe_parts = self._split_params(oe_params)
                ec_ref = self._ref(oe_parts[3])
                oe_forward = oe_parts[4].strip() == '.T.'

                _, ec_params = self.entities[ec_ref]
                ec_parts = self._split_params(ec_params)
                sv = self._ref(ec_parts[1])
                ev = self._ref(ec_parts[2])
                curve_ref = self._ref(ec_parts[3])
                ctype, _ = self.entities[curve_ref]

                start_3d = self._get_vertex_coords(sv)
                end_3d = self._get_vertex_coords(ev)
                if not oe_forward:
                    start_3d, end_3d = end_3d, start_3d

                if ctype == 'LINE':
                    edges.append((
                        [start_3d[0], end_3d[0]],
                        [start_3d[1], end_3d[1]],
                        [start_3d[2], end_3d[2]],
                    ))
                elif ctype == 'CIRCLE':
                    center_3d, radius, placement_ref = self._get_circle_info(curve_ref)
                    # Sample arc points
                    cx, cy, cz = center_3d
                    sx, sy, sz = start_3d
                    ex, ey, ez = end_3d

                    a_start = math.atan2(sy - cy, sx - cx)
                    a_end = math.atan2(ey - cy, ex - cx)

                    # Determine sweep direction
                    try:
                        axis_z = self._get_placement_axis_z(placement_ref)
                    except (KeyError, IndexError):
                        axis_z = 1.0
                    ec_same_sense = ec_parts[4].strip() == '.T.'
                    is_ccw = axis_z > 0
                    if not ec_same_sense:
                        is_ccw = not is_ccw
                    if not oe_forward:
                        is_ccw = not is_ccw

                    if is_ccw:
                        if a_end <= a_start:
                            a_end += 2 * math.pi
                    else:
                        if a_start <= a_end:
                            a_start += 2 * math.pi

                    n_pts = max(20, int(abs(a_end - a_start) / (math.pi / 30)))
                    angles = [a_start + (a_end - a_start) * t / n_pts for t in range(n_pts + 1)]

                    # Z interpolation for 3D arcs on cylindrical surfaces
                    xs = [cx + radius * math.cos(a) for a in angles]
                    ys = [cy + radius * math.sin(a) for a in angles]
                    if abs(sz - ez) < 0.001:
                        zs = [sz] * len(angles)
                    else:
                        zs = [sz + (ez - sz) * t / n_pts for t in range(n_pts + 1)]
                    edges.append((xs, ys, zs))

        return edges

    def _process_oriented_edge(self, oe_id: int) -> Optional[Segment]:
        """Convert an ORIENTED_EDGE to a 2D segment (line or arc)."""
        _, params = self.entities[oe_id]
        parts = self._split_params(params)

        edge_curve_ref = self._ref(parts[3])
        oe_forward = parts[4].strip() == '.T.'

        # Parse EDGE_CURVE
        _, ec_params = self.entities[edge_curve_ref]
        ec_parts = self._split_params(ec_params)
        start_vertex = self._ref(ec_parts[1])
        end_vertex = self._ref(ec_parts[2])
        curve_ref = self._ref(ec_parts[3])
        ec_same_sense = ec_parts[4].strip() == '.T.'

        # Get 3D coordinates
        start_3d = self._get_vertex_coords(start_vertex)
        end_3d = self._get_vertex_coords(end_vertex)

        # Apply oriented edge direction (swap if reversed)
        if not oe_forward:
            start_3d, end_3d = end_3d, start_3d

        start = Point2D(start_3d[0], start_3d[1])
        end = Point2D(end_3d[0], end_3d[1])

        curve_type, _ = self.entities[curve_ref]

        if curve_type == 'LINE':
            return LineSeg(start=start, end=end)
        elif curve_type == 'CIRCLE':
            center_3d, radius, placement_ref = self._get_circle_info(curve_ref)
            center = Point2D(center_3d[0], center_3d[1])

            # Determine arc direction:
            # Base: circle axis +Z → CCW positive
            axis_z = self._get_placement_axis_z(placement_ref)
            is_ccw = axis_z > 0

            # Flip for edge_curve same_sense
            if not ec_same_sense:
                is_ccw = not is_ccw
            # Flip for oriented_edge direction
            if not oe_forward:
                is_ccw = not is_ccw

            clockwise = not is_ccw
            return ArcSeg(start=start, end=end, center=center,
                          radius=radius, clockwise=clockwise)

        return None

    def get_plate_center(self, contours: List[Contour]) -> Point2D:
        """Calculate the center of the plate from the outer contour bounds."""
        for c in contours:
            if not c.is_hole:
                b = c.bounds
                return Point2D((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        # Fallback: use all contours
        all_x, all_y = [], []
        for c in contours:
            b = c.bounds
            all_x.extend([b[0], b[2]])
            all_y.extend([b[1], b[3]])
        return Point2D((min(all_x) + max(all_x)) / 2,
                       (min(all_y) + max(all_y)) / 2)
