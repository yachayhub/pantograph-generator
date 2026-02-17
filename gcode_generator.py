"""
G-code generator for Messer plasma pantograph cutting machines.
Generates incremental (G91) G-code from 2D contours extracted by step_parser.
Output format matches the Messer Plasma CNC format with G261/G260 pierce blocks.
"""

import math
import re
from typing import List, Optional
from step_parser import Point2D, LineSeg, ArcSeg, Contour, Segment


def generate_gcode(
    contours: List[Contour],
    part_name: str = "1001",
    plate_center: Optional[Point2D] = None,
    lead_in_length: float = 5.0,
    lead_in_angle: float = 60.0,  # degrees from tangent
    decimals: int = 2,
) -> str:
    """
    Generate Messer plasma G-code from contours.

    Args:
        contours: List of Contour objects (holes first, then outer).
        part_name: Part name for the header.
        plate_center: Center of the plate (used as G-code origin).
        lead_in_length: Length of the lead-in/lead-out approach (mm).
        lead_in_angle: Angle of approach relative to first cut direction (degrees).
        decimals: Number of decimal places in output coordinates.
    """
    if plate_center is None:
        plate_center = Point2D(0, 0)

    lines = []

    # --- Header ---
    lines.append(f"(%%INFO PartName={part_name})")
    lines.append("G21")
    lines.append("G70")
    lines.append("G91")
    lines.append("G92 X0 Y0 Z0")
    lines.append("(End Header)")
    lines.append("G54")
    lines.append("G162")
    lines.append("G141")
    lines.append("G237")
    lines.append("#CS ON [V.E.START_X, V.E.START_Y, 0, 0, 0, V.E.ROTATION]")
    lines.append("M190")

    # Track absolute position (in plate-center coordinates)
    abs_x, abs_y = 0.0, 0.0
    tool_set = False

    def fmt(v: float) -> str:
        return f"{round(v, decimals)}"

    def rapid_to(x: float, y: float) -> str:
        nonlocal abs_x, abs_y
        dx = x - abs_x
        dy = y - abs_y
        abs_x, abs_y = x, y
        parts = ["G00"]
        if abs(dx) > 0.001:
            parts.append(f"X{fmt(dx)}")
        if abs(dy) > 0.001:
            parts.append(f"Y{fmt(dy)}")
        if len(parts) == 1:
            parts.append("X0 Y0")
        return " ".join(parts)

    # --- Process each contour ---
    for contour in contours:
        if not contour.segments:
            continue

        # Transform contour to plate-center coordinates
        segs = _transform_contour(contour.segments, plate_center)

        # Calculate lead-in point and direction
        first_seg = segs[0]
        lead_start, lead_end = _calc_lead_in(
            first_seg, lead_in_length, lead_in_angle, contour.is_hole
        )

        # Rapid to lead-in start
        lines.append(rapid_to(lead_start.x, lead_start.y))

        # Tool selection (once)
        if not tool_set:
            lines.append("T1")
            tool_set = True

        # Torch ON + Pierce
        lines.append("M07")
        lines.append("G261")

        # Lead-in move
        dx = lead_end.x - abs_x
        dy = lead_end.y - abs_y
        abs_x, abs_y = lead_end.x, lead_end.y
        lines.append(f"G01 X{fmt(dx)} Y{fmt(dy)}")

        # Cut segments
        for seg in segs:
            if isinstance(seg, LineSeg):
                dx = seg.end.x - abs_x
                dy = seg.end.y - abs_y
                abs_x, abs_y = seg.end.x, seg.end.y
                if abs(dx) > 0.001 or abs(dy) > 0.001:
                    parts = ["G01"]
                    parts.append(f"X{fmt(dx)}")
                    parts.append(f"Y{fmt(dy)}")
                    lines.append(" ".join(parts))
            elif isinstance(seg, ArcSeg):
                dx = seg.end.x - abs_x
                dy = seg.end.y - abs_y
                # I, J = offset from current pos to center
                ci = seg.center.x - abs_x
                cj = seg.center.y - abs_y
                abs_x, abs_y = seg.end.x, seg.end.y
                g_code = "G02" if seg.clockwise else "G03"
                lines.append(
                    f"{g_code} X{fmt(dx)} Y{fmt(dy)} I{fmt(ci)} J{fmt(cj)}"
                )

        # Lead-out move
        last_seg = segs[-1]
        lead_out_start, lead_out_end = _calc_lead_out(
            last_seg, lead_in_length, lead_in_angle, contour.is_hole
        )
        dx = lead_out_end.x - abs_x
        dy = lead_out_end.y - abs_y
        abs_x, abs_y = lead_out_end.x, lead_out_end.y
        lines.append(f"G01 X{fmt(dx)} Y{fmt(dy)}")

        # Pierce end + Torch OFF
        lines.append("G260")
        lines.append("M08")

        # Rapid to origin-relative position (no actual move)
        lines.append("G00 X0 Y0")

    # --- Footer ---
    lines.append("G40")
    lines.append("T0")
    lines.append("#CS OFF")
    lines.append("M30")

    return "\n".join(lines) + "\n"


def _transform_contour(
    segments: List[Segment], center: Point2D
) -> List[Segment]:
    """Transform contour segments to plate-center coordinate system."""
    result = []
    for seg in segments:
        if isinstance(seg, LineSeg):
            result.append(LineSeg(
                start=Point2D(seg.start.x - center.x, seg.start.y - center.y),
                end=Point2D(seg.end.x - center.x, seg.end.y - center.y),
            ))
        elif isinstance(seg, ArcSeg):
            result.append(ArcSeg(
                start=Point2D(seg.start.x - center.x, seg.start.y - center.y),
                end=Point2D(seg.end.x - center.x, seg.end.y - center.y),
                center=Point2D(seg.center.x - center.x, seg.center.y - center.y),
                radius=seg.radius,
                clockwise=seg.clockwise,
            ))
    return result


def _calc_lead_in(
    first_seg: Segment, length: float, angle_deg: float, is_hole: bool
) -> tuple:
    """Calculate lead-in start and end points."""
    # Direction of the first segment
    dx = first_seg.end.x - first_seg.start.x
    dy = first_seg.end.y - first_seg.start.y
    seg_len = math.sqrt(dx**2 + dy**2)
    if seg_len < 0.001:
        dx, dy = 1.0, 0.0
    else:
        dx, dy = dx / seg_len, dy / seg_len

    # Rotate lead-in direction by angle from the cut direction
    angle_rad = math.radians(angle_deg)
    # For holes, approach from inside; for outer, from outside
    sign = 1 if is_hole else -1
    cos_a = math.cos(sign * angle_rad)
    sin_a = math.sin(sign * angle_rad)
    lead_dx = dx * cos_a - dy * sin_a
    lead_dy = dx * sin_a + dy * cos_a

    # Lead-in end is at the start of the first segment
    lead_end = first_seg.start
    # Lead-in start is offset backwards
    lead_start = Point2D(
        lead_end.x - lead_dx * length,
        lead_end.y - lead_dy * length
    )
    return lead_start, lead_end


def _calc_lead_out(
    last_seg: Segment, length: float, angle_deg: float, is_hole: bool
) -> tuple:
    """Calculate lead-out start and end points."""
    dx = last_seg.end.x - last_seg.start.x
    dy = last_seg.end.y - last_seg.start.y
    seg_len = math.sqrt(dx**2 + dy**2)
    if seg_len < 0.001:
        dx, dy = 1.0, 0.0
    else:
        dx, dy = dx / seg_len, dy / seg_len

    angle_rad = math.radians(angle_deg)
    sign = -1 if is_hole else 1
    cos_a = math.cos(sign * angle_rad)
    sin_a = math.sin(sign * angle_rad)
    lead_dx = dx * cos_a - dy * sin_a
    lead_dy = dx * sin_a + dy * cos_a

    lead_start = last_seg.end
    lead_end = Point2D(
        lead_start.x + lead_dx * length,
        lead_start.y + lead_dy * length
    )
    return lead_start, lead_end


def gcode_to_absolute_path(gcode: str) -> List[dict]:
    """Parse G-code back to absolute coordinates for visualization."""
    points = []
    x, y = 0.0, 0.0
    points.append({'x': x, 'y': y, 'type': 'start'})

    for line in gcode.split('\n'):
        line = line.strip()
        if not line or line.startswith('(') or line.startswith('#'):
            continue

        # Extract G-code and parameters
        g_match = re.match(r'(G\d+)', line) if 'G' in line else None
        if not g_match:
            continue

        g_code = g_match.group(1)

        x_match = re.search(r'X([-+]?[0-9]*\.?[0-9]+)', line)
        y_match = re.search(r'Y([-+]?[0-9]*\.?[0-9]+)', line)

        dx = float(x_match.group(1)) if x_match else 0
        dy = float(y_match.group(1)) if y_match else 0

        if g_code in ('G00', 'G01', 'G02', 'G03'):
            move_type = 'rapid' if g_code == 'G00' else 'cut'
            if g_code in ('G02', 'G03'):
                move_type = 'arc_cw' if g_code == 'G02' else 'arc_ccw'
                i_match = re.search(r'I([-+]?[0-9]*\.?[0-9]+)', line)
                j_match = re.search(r'J([-+]?[0-9]*\.?[0-9]+)', line)
                ci = float(i_match.group(1)) if i_match else 0
                cj = float(j_match.group(1)) if j_match else 0
                cx = x + ci
                cy = y + cj
                points.append({
                    'x': x + dx, 'y': y + dy, 'type': move_type,
                    'cx': cx, 'cy': cy, 'sx': x, 'sy': y,
                })
            else:
                points.append({'x': x + dx, 'y': y + dy, 'type': move_type})
            x += dx
            y += dy

    return points
