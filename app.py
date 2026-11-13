import streamlit as st
import duckdb
import pandas as pd
from datetime import datetime, date
import gc  # RECOLECTOR DE BASURA (Evita congelamientos)

# ==============================================================================
# CONFIGURACIÓN GENERAL Y ESTILOS
# ==============================================================================
st.set_page_config(
    page_title="Consola Operativa WFM: Consola Maestra GTR",
    page_icon="🎧",
    layout="wide",
    initial_sidebar_state="collapsed"
)

if "tema_visual" not in st.session_state:
    st.session_state["tema_visual"] = "Oscuro"

if "version_datos" not in st.session_state:
    st.session_state["version_datos"] = 1

# ==============================================================================
# LÓGICA DINÁMICA DE TEMAS VISUALES Y UI MODERNA (CON PESTAÑA ACTIVA ILUMINADA)
# ==============================================================================
tema = st.session_state["tema_visual"]

if tema == "Oscuro":
    css_colores = """
    .stApp {
        background: linear-gradient(rgba(10, 15, 30, 0.94), rgba(10, 15, 30, 0.94)), url("https://images.unsplash.com/photo-1527066579998-dbbae57f45ce?q=80&w=1920&auto=format&fit=crop");
        background-size: cover; background-attachment: fixed;
    }
    """
elif tema == "Claro":
    css_colores = """
    .stApp { background: linear-gradient(135deg, #F8FAFC 0%, #E2E8F0 100%); }
    .stMarkdown, p, h1, h2, h3, h4, h5, span { color: #0F172A !important; }
    """
else:
    css_colores = """
    .stApp { background: linear-gradient(135deg, #334155 0%, #0F172A 100%); }
    .stMarkdown, p, h1, h2, h3, h4, h5, span { color: #F8FAFC !important; }
    """

st.markdown(f"""
<style>
    {css_colores}
    .block-container {{ padding-top: 1.5rem !important; max-width: 98% !important; }}
    #MainMenu {{visibility: hidden;}}
    header {{visibility: hidden;}}
    
    div[data-testid="stRadio"] {{
        background: rgba(15, 23, 42, 0.55) !important; padding: 14px 18px !important;
        border-radius: 20px !important; border: 1px solid rgba(56, 189, 248, 0.25) !important;
        backdrop-filter: blur(15px) !important; box-shadow: 0 8px 30px rgba(0, 0, 0, 0.35) !important;
        margin-bottom: 25px !important;
    }}
    div[data-testid="stRadio"] > div[role="radiogroup"] {{ gap: 12px !important; display: flex !important; flex-wrap: wrap !important; }}
    div[data-testid="stRadio"] label {{
        background: rgba(30, 41, 59, 0.78) !important; border: 1.5px solid rgba(56, 189, 248, 0.25) !important;
        border-radius: 14px !important; padding: 11px 22px !important; box-shadow: 0 4px 15px rgba(0,0,0,0.25) !important;
        transition: all 0.22s ease !important; cursor: pointer !important;
    }}
    /* Efecto al pasar el mouse (Hover) */
    div[data-testid="stRadio"] label:hover {{
        background: rgba(56, 189, 248, 0.22) !important; border-color: #38BDF8 !important;
        transform: translateY(-2px) !important; box-shadow: 0 6px 22px rgba(56, 189, 248, 0.38) !important;
    }}
    /* Efecto permanente cuando estamos dentro del módulo (Activo / Seleccionado) */
    div[data-testid="stRadio"] label:has(input:checked),
    div[data-testid="stRadio"] label[data-checked="true"] {{
        background: linear-gradient(135deg, rgba(14, 165, 233, 0.35) 0%, rgba(59, 130, 246, 0.45) 100%) !important;
        border: 2px solid #38BDF8 !important;
        box-shadow: 0 0 22px rgba(56, 189, 248, 0.55), inset 0 0 12px rgba(56, 189, 248, 0.25) !important;
        transform: translateY(-2px) !important;
    }}
    div[data-testid="stRadio"] label:has(input:checked) p,
    div[data-testid="stRadio"] label[data-checked="true"] p {{
        color: #FFFFFF !important;
        text-shadow: 0 0 10px rgba(56, 189, 248, 0.8) !important;
    }}
    div[data-testid="stRadio"] input[type="radio"] {{ display: none !important; }}
    div[data-testid="stRadio"] label p {{ font-weight: 800 !important; font-size: 0.96rem !important; margin: 0 !important; color: #F8FAFC !important; }}

    [data-testid="stFileUploader"] {{
        background: rgba(15, 23, 42, 0.6) !important; backdrop-filter: blur(10px) !important;
        border: 2px dashed rgba(56, 189, 248, 0.4) !important; border-radius: 20px !important;
        padding: 20px !important; transition: all 0.2s ease !important;
    }}
    [data-testid="stFileUploader"]:hover {{
        background: rgba(30, 41, 59, 0.8) !important; border-color: #38BDF8 !important;
        box-shadow: 0 8px 25px rgba(56, 189, 248, 0.25) !important; transform: translateY(-2px) !important;
    }}
    [data-testid="stFileUploader"] button {{ background: linear-gradient(135deg, #38BDF8 0%, #818CF8 100%) !important; color: white !important; border: none !important; border-radius: 8px !important; font-weight: 800 !important; }}
    
    div.stButton > button[kind="primary"] {{
        background: linear-gradient(135deg, #10B981 0%, #059669 100%) !important; border: none !important; color: white !important;
        padding: 20px !important; font-size: 1.3rem !important; font-weight: 900 !important; border-radius: 16px !important;
        box-shadow: 0 8px 20px rgba(16, 185, 129, 0.4) !important; transition: all 0.2s ease !important;
    }}
    div.stButton > button[kind="primary"]:hover {{ transform: translateY(-2px) !important; box-shadow: 0 12px 25px rgba(16, 185, 129, 0.6) !important; }}
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# CONEXIÓN DUCKDB GLOBAL CON SEGUROS ANTI-CONGELAMIENTO
# ==============================================================================
@st.cache_resource
def obtener_conexion_db():
    conexion = duckdb.connect(database="callcenter.duckdb", read_only=False)
    conexion.execute("PRAGMA threads=4;")
    conexion.execute("PRAGMA memory_limit='2GB';")
    conexion.execute("""
        CREATE TABLE IF NOT EXISTS archivos_cargados_log (
            nombre_archivo VARCHAR PRIMARY KEY,
            modulo VARCHAR,
            filas INTEGER,
            fecha_carga VARCHAR
        );
    """)
    return conexion

con = obtener_conexion_db()

try:
    import modulo_usuarios
    modulo_usuarios.inicializar_tabla_usuarios(con)
except Exception:
    pass

if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False

# ==============================================================================
# FLUJO DE NAVEGACIÓN Y AUTENTICACIÓN POR ROLES (ADMIN vs LECTOR)
# ==============================================================================
if not st.session_state["autenticado"]:
    import modulo_login
    modulo_login.renderizar_login(con)
else:
    usuario_actual = st.session_state.get("usuario_actual", "GTR")
    rol_actual = st.session_state.get("rol_actual", "Administrador GTR")
    es_admin = (
        st.session_state.get("permiso_wfm", "ADMIN") == "ADMIN"
        or str(usuario_actual).strip().upper() == "GTR"
        or "ADMIN" in str(rol_actual).upper()
    )
    st.session_state["es_admin_wfm"] = es_admin

    c_title_l, c_title_m, c_theme, c_logout = st.columns([2.7, 1.1, 1.0, 1.0])
    
    with c_title_l:
        st.title("🎧 Consola Operativa WFM")
        badge_permiso = "🛡️ Modo Administrador Total" if es_admin else "👁️ Modo Visualización y Descarga"
        st.caption(f"Bienvenido, **{usuario_actual}** ({rol_actual}) &bull; {badge_permiso} | Consola Maestra Aguas Andinas")

    with c_title_m:
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        if "fecha_activa_dt" not in st.session_state:
            st.session_state["fecha_activa_dt"] = date.today()

        fecha_operativa = st.date_input(
            "📅 Fecha Operativa:",
            value=st.session_state["fecha_activa_dt"],
            key="selector_fecha_global"
        )
        fecha_activa_str = fecha_operativa.strftime("%Y-%m-%d")
        st.session_state["fecha_activa_dt"] = fecha_operativa
        st.session_state["fecha_activa_str"] = fecha_activa_str

    with c_theme:
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        st.selectbox("🌓 Apariencia:", ["Oscuro", "Intermedio", "Claro"], key="tema_visual")

    with c_logout:
        st.markdown("<div style='height: 39px;'></div>", unsafe_allow_html=True)
        if st.button("🚪 Cerrar Sesión", width="stretch"):
            st.session_state["autenticado"] = False
            st.session_state.pop("usuario_actual", None)
            st.session_state.pop("rol_actual", None)
            st.session_state.pop("permiso_wfm", None)
            st.rerun()

    st.markdown("---")

    # ==============================================================================
    # ESCÁNER GLOBAL DE INGESTA AUTOMÁTICA EN SEGUNDO PLANO (UNA SOLA VEZ)
    # ==============================================================================
    if "autocarga_global_lista" not in st.session_state:
        import modulo_ingesta
        archivos_precargados = modulo_ingesta.precargar_archivos_locales(con, fecha_activa_str)
        if archivos_precargados:
            st.toast("🤖 BBDD y Mallas pre-cargadas automáticamente.", icon="🚀")
        st.session_state["autocarga_global_lista"] = True

    # ==============================================================================
    # NAVEGACIÓN MODERNA SEGÚN PERMISOS DEL USUARIO
    # ==============================================================================
    if es_admin:
        tabs_nombres = [
            "⚙️ Ingesta de Datos",
            "⏱️ Control Intervalos",
            "🍱 Planificación Breaks",
            "📈 Productividad TMO",
            "🚻 Monitor de Pausas",
            "👥 Asist. y Comparativo",
            "📊 Rentabilidad PCE",
            "📋 BD Ejecutivos",
            "🔐 Creador de Usuarios"
        ]
    else:
        tabs_nombres = [
            "⏱️ Control Intervalos",
            "🍱 Planificación Breaks",
            "📈 Productividad TMO",
            "🚻 Monitor de Pausas",
            "👥 Asist. y Comparativo",
            "📊 Rentabilidad PCE",
            "📋 BD Ejecutivos"
        ]
    
    tab_activa = st.radio(
        "Sección Operativa:",
        tabs_nombres,
        horizontal=True,
        label_visibility="collapsed"
    )

    # ==============================================================================
    # ENRUTADOR CON IMPORTACIONES PEREZOSAS
    # ==============================================================================
    if tab_activa == "⚙️ Ingesta de Datos" and es_admin:
        import modulo_ingesta
        modulo_ingesta.renderizar_ingesta(con, fecha_activa_str)

    elif tab_activa == "⏱️ Control Intervalos":
        import modulo_intervalos_vivo
        modulo_intervalos_vivo.renderizar_modulo_intervalos(con, fecha_activa_str)

    elif tab_activa == "🍱 Planificación Breaks":
        import modulo_colaciones_break_asistencia
        modulo_colaciones_break_asistencia.renderizar_modulo_colaciones_asistencia(con, fecha_activa_str)

    elif tab_activa == "📈 Productividad TMO":
        try:
            import modulo_productividad_tmo
            modulo_productividad_tmo.renderizar_modulo_productividad(con, fecha_activa_str)
        except ImportError:
            st.error("🚨 Falta el archivo del módulo de Productividad.")

    elif tab_activa == "🚻 Monitor de Pausas":
        import modulo_monitor_pausas
        modulo_monitor_pausas.renderizar_modulo_monitor_pausas(con, fecha_activa_str)

    elif tab_activa == "👥 Asist. y Comparativo":
        import modulo_asistencia_comparativo
        modulo_asistencia_comparativo.renderizar_modulo_asistencia_comparativo(con, fecha_activa_str)

    elif tab_activa == "📊 Rentabilidad PCE":
        try:
            import modulo_rentabilidad_cybel
            modulo_rentabilidad_cybel.renderizar_modulo_cybel(con, fecha_activa_str)
        except ImportError:
            st.error("🚨 Falta el archivo modulo_rentabilidad_cybel.py.")

    elif tab_activa == "📋 BD Ejecutivos":
        import modulo_base_ejecutivos
        modulo_base_ejecutivos.renderizar_modulo_base_ejecutivos(con, fecha_activa_str)

    elif tab_activa == "🔐 Creador de Usuarios" and es_admin:
        import modulo_usuarios
        modulo_usuarios.renderizar_modulo_usuarios(con)

    # ==============================================================================
    # LIMPIEZA DE BASURA EN RAM
    # ==============================================================================
    gc.collect()