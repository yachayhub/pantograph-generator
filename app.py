"""
Pantograph Cutting File Generator — Streamlit Application
Generates Messer plasma pantograph cutting files from STEP files.
"""

import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import plotly.graph_objects as go
import numpy as np
import math
import tempfile
import os

from step_parser import StepParser, Point2D, LineSeg, ArcSeg, Contour
from gcode_generator import generate_gcode, gcode_to_absolute_path
from matplotlib.lines import Line2D


# --- Helper plotting functions ---

def _plot_arc(ax, seg: ArcSeg, color: str, linewidth: float = 2):
    cx, cy = seg.center.x, seg.center.y
    r = seg.radius
    start_angle = math.degrees(math.atan2(seg.start.y - cy, seg.start.x - cx))
    end_angle = math.degrees(math.atan2(seg.end.y - cy, seg.end.x - cx))
    if seg.clockwise:
        if start_angle < end_angle:
            start_angle += 360
    else:
        if end_angle < start_angle:
            end_angle += 360
    angles = np.linspace(start_angle, end_angle, 100)
    xs = cx + r * np.cos(np.radians(angles))
    ys = cy + r * np.sin(np.radians(angles))
    ax.plot(xs, ys, color=color, linewidth=linewidth, solid_capstyle='round')


def _plot_gcode_arc(ax, point: dict, prev_point: dict, linewidth: float = 2):
    sx, sy = prev_point['x'], prev_point['y']
    ex, ey = point['x'], point['y']
    cx, cy = point['cx'], point['cy']
    r = math.sqrt((sx - cx)**2 + (sy - cy)**2)
    start_angle = math.degrees(math.atan2(sy - cy, sx - cx))
    end_angle = math.degrees(math.atan2(ey - cy, ex - cx))
    is_cw = point['type'] == 'arc_cw'
    color = '#64ffda'
    if is_cw:
        if start_angle < end_angle:
            start_angle += 360
    else:
        if end_angle < start_angle:
            end_angle += 360
    angles = np.linspace(start_angle, end_angle, 100)
    xs = cx + r * np.cos(np.radians(angles))
    ys = cy + r * np.sin(np.radians(angles))
    ax.plot(xs, ys, color=color, linewidth=linewidth, solid_capstyle='round')


def build_3d_figure(faces_3d, selected_face_id=None):
    """Build an interactive Plotly 3D wireframe figure."""
    fig = go.Figure()

    for face in faces_3d:
        fid = face['id']
        is_selected = (fid == selected_face_id)

        if is_selected:
            color = '#00e5ff'
            width = 5
            opacity = 1.0
        elif face['is_cuttable']:
            color = '#ffab40'
            width = 3
            opacity = 0.85
        else:
            color = '#78909c'
            width = 1.5
            opacity = 0.5

        for xs, ys, zs in face['edges_3d']:
            fig.add_trace(go.Scatter3d(
                x=xs, y=ys, z=zs,
                mode='lines',
                line=dict(color=color, width=width),
                opacity=opacity,
                hoverinfo='text',
                text=f"Cara #{fid} ({face['surface_type']})",
                showlegend=False,
            ))

    fig.update_layout(
        scene=dict(
            xaxis=dict(title='X (mm)', backgroundcolor='#1a2332',
                       gridcolor='#2d3f54', zerolinecolor='#2d3f54',
                       color='#b0bec5', title_font=dict(color='#e0e0e0')),
            yaxis=dict(title='Y (mm)', backgroundcolor='#1a2332',
                       gridcolor='#2d3f54', zerolinecolor='#2d3f54',
                       color='#b0bec5', title_font=dict(color='#e0e0e0')),
            zaxis=dict(title='Z (mm)', backgroundcolor='#1a2332',
                       gridcolor='#2d3f54', zerolinecolor='#2d3f54',
                       color='#b0bec5', title_font=dict(color='#e0e0e0')),
            aspectmode='data',
            bgcolor='#1a2332',
        ),
        paper_bgcolor='#1a2332',
        margin=dict(l=0, r=0, t=30, b=0),
        height=500,
    )
    return fig


# --- Page Config ---
st.set_page_config(
    page_title="Generador de Archivos de Corte — Pantógrafo",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Custom CSS (improved contrast) ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    .stApp {
        background: linear-gradient(135deg, #121e2e 0%, #1a2b3d 50%, #121e2e 100%);
        color: #e0e6ed;
        font-family: 'Inter', sans-serif;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a2b3d, #121e2e);
        border-right: 1px solid #2d4055;
    }
    section[data-testid="stSidebar"] .stMarkdown h1,
    section[data-testid="stSidebar"] .stMarkdown h2,
    section[data-testid="stSidebar"] .stMarkdown h3 { color: #00e5ff; }
    section[data-testid="stSidebar"] .stMarkdown p,
    section[data-testid="stSidebar"] .stMarkdown li { color: #c5cdd8; }
    section[data-testid="stSidebar"] label { color: #c5cdd8 !important; }

    /* File uploader */
    [data-testid="stFileUploader"] {
        border: 2px dashed #3d5a80;
        border-radius: 12px;
        padding: 10px;
        transition: border-color 0.3s ease;
    }
    [data-testid="stFileUploader"]:hover { border-color: #00e5ff; }

    /* Cards */
    .metric-card {
        background: linear-gradient(135deg, #1e3048, #243b55);
        border: 1px solid #3d5a80;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
    }
    .metric-value { font-size: 2rem; font-weight: 700; color: #00e5ff; }
    .metric-label { font-size: 0.85rem; color: #b0bec5; margin-top: 5px; }

    .success-box {
        background: linear-gradient(135deg, #0d3320, #145230);
        border: 1px solid #2ecc71;
        border-radius: 12px;
        padding: 20px;
        margin: 15px 0;
    }

    .face-card {
        background: linear-gradient(135deg, #1e3048, #243b55);
        border: 1px solid #3d5a80;
        border-radius: 12px;
        padding: 15px;
        margin: 8px 0;
    }
    .face-card.selected {
        border-color: #00e5ff;
        box-shadow: 0 0 20px rgba(0, 229, 255, 0.2);
    }

    /* Text */
    h1, h2, h3 { color: #e8edf2 !important; }
    p, span, label, div { color: #d0d8e0; }

    /* Tabs */
    .stTabs [data-baseweb="tab"] { color: #b0bec5; }
    .stTabs [aria-selected="true"] { color: #00e5ff !important; }

    /* Radio buttons */
    .stRadio label span { color: #d0d8e0 !important; }

    /* Number inputs */
    .stNumberInput label { color: #c5cdd8 !important; }

    /* Footer */
    .footer {
        text-align: center;
        color: #6b7c8e;
        font-size: 0.8rem;
        margin-top: 50px;
        padding: 20px;
        border-top: 1px solid #2d4055;
    }

    /* Code blocks */
    .stCodeBlock { background: #1a2332 !important; }

    /* Info text */
    .info-text { color: #b0bec5; font-size: 0.85rem; }
    .highlight { color: #00e5ff; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# --- Sidebar ---
with st.sidebar:
    st.markdown("# 🔥 Pantógrafo")
    st.markdown("### Parámetros de Corte")

    cut_speed = st.number_input("Velocidad de corte (mm/min)", value=1500, step=100, min_value=100)
    plate_thickness = st.number_input("Espesor de placa (mm)", value=20.0, step=0.5, min_value=1.0)
    lead_in_radius = st.number_input("Radio de entrada (mm)", value=5.0, step=0.5, min_value=1.0)
    kerf = st.number_input("Kerf / sangría (mm)", value=2.0, step=0.1, min_value=0.0)

    st.markdown("---")
    st.markdown("### Información")
    st.markdown("""
    **Formatos soportados:**
    - 📁 Archivos STEP (.step, .stp)

    **Salida:**
    - G-code formato Messer
    """)

# --- Main Content ---
st.markdown("# 🏭 Generador de Archivos de Corte")
st.markdown("#### Pantógrafo Plasma Messer")

uploaded_file = st.file_uploader(
    "Sube tu archivo STEP (.step, .stp)",
    type=["step", "stp"],
    help="Archivo CAD en formato STEP (ISO 10303-21)"
)

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix='.step') as tmp:
        tmp.write(uploaded_file.read())
        tmp_path = tmp.name

    try:
        parser = StepParser(tmp_path)
        faces_3d = parser.extract_all_faces_3d()
        cuttable_faces = [f for f in faces_3d if f['is_cuttable']]

        st.markdown("---")

        # === STAGE 1: 3D Preview + Face Selection ===
        st.markdown("## 🔍 Vista 3D del Sólido")

        col_3d, col_select = st.columns([2, 1])

        with col_select:
            st.markdown("### 🎯 Seleccionar cara de corte")

            if not cuttable_faces:
                st.error("❌ No se encontraron caras planas cortables")
                st.stop()

            face_options = {}
            for f in cuttable_faces:
                dims = f['dimensions']
                dims_str = f"{dims[0]} × {dims[1]} mm" if dims else "?"
                holes_str = f"{f['num_holes']} agujero{'s' if f['num_holes'] != 1 else ''}"
                label = f"Z = {f['z_level']:.1f} mm — {dims_str} — {holes_str}"
                face_options[label] = f['id']

            selected_label = st.radio(
                "Caras planas disponibles:",
                options=list(face_options.keys()),
                index=0,
            )
            selected_face_id = face_options[selected_label]

            sel_face = next(f for f in cuttable_faces if f['id'] == selected_face_id)
            st.markdown(f"""
            <div class="face-card selected">
                <div class="highlight" style="font-size: 1rem;">✓ Cara seleccionada</div>
                <div style="color: #e0e6ed; margin-top: 10px; line-height: 1.8;">
                    <b>Nivel Z:</b> {sel_face['z_level']:.1f} mm<br>
                    <b>Dimensiones:</b> {sel_face['dimensions'][0]} × {sel_face['dimensions'][1]} mm<br>
                    <b>Agujeros:</b> {sel_face['num_holes']}<br>
                    <b>Bordes:</b> {len(sel_face['edges_3d'])} segmentos
                </div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown(f"""
            <div style="margin-top: 15px; line-height: 1.6;" class="info-text">
                <b>Total caras:</b> {len(faces_3d)}<br>
                <b>Planas cortables:</b> <span class="highlight">{len(cuttable_faces)}</span><br>
                <b>Cilíndricas/laterales:</b> {len(faces_3d) - len(cuttable_faces)}
            </div>
            """, unsafe_allow_html=True)

        with col_3d:
            fig_3d = build_3d_figure(faces_3d, selected_face_id)
            st.plotly_chart(fig_3d, use_container_width=True, key="3d_viewer")

        # === STAGE 2: Extract contours and generate G-code ===
        st.markdown("---")
        st.markdown("## ✂️ Resultado de Corte")

        contours = parser.extract_contours(face_id=selected_face_id)

        if not contours:
            st.error("No se pudieron extraer contornos de la cara seleccionada")
            st.stop()

        outer = [c for c in contours if not c.is_hole]
        holes = [c for c in contours if c.is_hole]
        dims = outer[0].bounds if outer else (0, 0, 0, 0)
        width = round(dims[2] - dims[0], 1)
        height = round(dims[3] - dims[1], 1)

        m1, m2, m3, m4 = st.columns(4)
        metrics = [
            ("Contornos", str(len(contours)), m1),
            ("Agujeros", str(len(holes)), m2),
            ("Ancho", f"{width} mm", m3),
            ("Alto", f"{height} mm", m4),
        ]
        for label, value, col in metrics:
            col.markdown(f"""
            <div class="metric-card">
                <div class="metric-value">{value}</div>
                <div class="metric-label">{label}</div>
            </div>
            """, unsafe_allow_html=True)

        plate_center = parser.get_plate_center(contours)
        gcode = generate_gcode(
            contours,
            plate_center=plate_center,
            lead_in_length=lead_in_radius,
        )

        tab1, tab2, tab3 = st.tabs([
            "🖼️ Vista de Contornos",
            "✂️ Trayectorias de Corte",
            "📝 G-code"
        ])

        with tab1:
            fig, ax = plt.subplots(1, 1, figsize=(10, 8), facecolor='#1a2332')
            ax.set_facecolor('#1a2332')
            colors = {'outer': '#00e5ff', 'hole': '#ff6b6b', 'start': '#ffd93d'}

            for contour in contours:
                color = colors['hole'] if contour.is_hole else colors['outer']
                for seg in contour.segments:
                    if isinstance(seg, LineSeg):
                        ax.plot([seg.start.x, seg.end.x], [seg.start.y, seg.end.y],
                                color=color, linewidth=2, solid_capstyle='round')
                    elif isinstance(seg, ArcSeg):
                        _plot_arc(ax, seg, color, linewidth=2)
                first = contour.segments[0]
                ax.plot(first.start.x, first.start.y, 'o', color=colors['start'],
                        markersize=6, zorder=5)

            ax.set_aspect('equal')
            ax.grid(True, alpha=0.15, color='#3d5a80')
            ax.set_xlabel('X (mm)', color='#b0bec5', fontsize=12)
            ax.set_ylabel('Y (mm)', color='#b0bec5', fontsize=12)
            ax.set_title(f'Contornos — Cara Z={sel_face["z_level"]:.1f} mm',
                         color='#e0e6ed', fontsize=14, fontweight='bold')
            ax.tick_params(colors='#b0bec5')
            for spine in ax.spines.values():
                spine.set_color('#3d5a80')

            legend_elements = [
                Line2D([0], [0], color=colors['outer'], linewidth=2, label='Contorno exterior'),
                Line2D([0], [0], color=colors['hole'], linewidth=2, label='Agujeros'),
                Line2D([0], [0], marker='o', color='w', markerfacecolor=colors['start'],
                       markersize=8, label='Punto inicio', linestyle='None'),
            ]
            ax.legend(handles=legend_elements, loc='upper right',
                      facecolor='#1e3048', edgecolor='#3d5a80', labelcolor='#e0e6ed')
            st.pyplot(fig)
            plt.close(fig)

        with tab2:
            path_points = gcode_to_absolute_path(gcode)
            fig2, ax2 = plt.subplots(1, 1, figsize=(10, 8), facecolor='#1a2332')
            ax2.set_facecolor('#1a2332')

            for i, p in enumerate(path_points):
                if p['type'] == 'start':
                    continue
                # Find previous point for start position
                prev = path_points[i - 1] if i > 0 else {'x': 0, 'y': 0}
                px, py = prev['x'], prev['y']

                if p['type'] == 'rapid':
                    ax2.plot([px, p['x']], [py, p['y']],
                             '--', color='#ffd93d', linewidth=1, alpha=0.5)
                elif p['type'] == 'cut':
                    ax2.plot([px, p['x']], [py, p['y']],
                             color='#00e5ff', linewidth=2, solid_capstyle='round')
                elif p['type'] in ('arc_cw', 'arc_ccw'):
                    _plot_gcode_arc(ax2, p, prev, linewidth=2)

            ax2.set_aspect('equal')
            ax2.grid(True, alpha=0.15, color='#3d5a80')
            ax2.set_xlabel('X (mm)', color='#b0bec5', fontsize=12)
            ax2.set_ylabel('Y (mm)', color='#b0bec5', fontsize=12)
            ax2.set_title('Trayectorias de Corte', color='#e0e6ed', fontsize=14, fontweight='bold')
            ax2.tick_params(colors='#b0bec5')
            for spine in ax2.spines.values():
                spine.set_color('#3d5a80')

            legend_elements2 = [
                Line2D([0], [0], color='#00e5ff', linewidth=2, label='Corte'),
                Line2D([0], [0], color='#ffd93d', linewidth=1, linestyle='--', label='Rápido'),
            ]
            ax2.legend(handles=legend_elements2, loc='upper right',
                       facecolor='#1e3048', edgecolor='#3d5a80', labelcolor='#e0e6ed')
            st.pyplot(fig2)
            plt.close(fig2)

        with tab3:
            st.code(gcode, language="gcode")

            st.download_button(
                label="📥 Descargar G-code",
                data=gcode,
                file_name=f"{os.path.splitext(uploaded_file.name)[0]}.txt",
                mime="text/plain",
            )

            st.markdown(f"""
            <div class="success-box">
                <div style="font-size: 1.2rem; font-weight: 600; color: #2ecc71;">
                    ✅ Archivo generado exitosamente
                </div>
                <div style="color: #e0e6ed; margin-top: 10px; line-height: 1.8;">
                    <b>Archivo:</b> {os.path.splitext(uploaded_file.name)[0]}.txt<br>
                    <b>Líneas:</b> {len(gcode.splitlines())}<br>
                    <b>Cara:</b> Z = {sel_face['z_level']:.1f} mm<br>
                    <b>Contornos:</b> {len(contours)} ({len(holes)} agujeros + {len(outer)} exterior)
                </div>
            </div>
            """, unsafe_allow_html=True)

    except Exception as e:
        st.error(f"Error procesando archivo: {str(e)}")
        import traceback
        st.code(traceback.format_exc())

    finally:
        os.unlink(tmp_path)

else:
    st.markdown("""
    <div style="text-align: center; padding: 60px 20px;">
        <div style="font-size: 4rem; margin-bottom: 20px;">📐</div>
        <div style="font-size: 1.3rem; margin-bottom: 10px; color: #e0e6ed;">
            Sube un archivo STEP para comenzar
        </div>
        <div style="font-size: 0.95rem; color: #b0bec5; line-height: 1.8;">
            El sistema extraerá la geometría 3D, te permitirá seleccionar la cara de corte<br>
            y generará el archivo G-code para el pantógrafo Messer
        </div>
    </div>
    """, unsafe_allow_html=True)

# Footer
st.markdown("""
<div class="footer">
    <div>🔥 Pantograph Cutting File Generator v2.0</div>
    <div>Streamlit • Plotly 3D • Formato Messer</div>
</div>
""", unsafe_allow_html=True)
