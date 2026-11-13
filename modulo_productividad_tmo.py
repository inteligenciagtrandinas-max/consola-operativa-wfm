import streamlit as st
import pandas as pd
import io
import re
import unicodedata
from datetime import datetime

pd.set_option("styler.render.max_elements", 2000000)

# ==============================================================================
# IMPORTACIÓN DE LIBRERÍAS GRÁFICAS
# ==============================================================================
try:
    import plotly.express as px
    import plotly.graph_objects as go
    HAY_PLOTLY = True
except ImportError:
    HAY_PLOTLY = False

# ==============================================================================
# CONSTANTES Y PARÁMETROS BASE WFM
# ==============================================================================
VALOR_POR_LLAMADA = 869
META_MENSUAL_VERDE_42H = 900000
META_MENSUAL_AMARILLO_42H = 800000
DIAS_HABILES_MES_BASE = 22

def normalizar_texto_nombre(texto):
    if pd.isna(texto) or not str(texto).strip():
        return ""
    s = str(texto).strip().upper()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^A-Z0-9\s]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

def normalizar_estado_agente(val):
    if pd.isna(val):
        return "ACTIVO"
    s = str(val).strip().upper()
    if not s or s in ["NAN", "NONE"]:
        return "ACTIVO"
    if any(k in s for k in ["BAJA", "RETIR", "FINIQ", "DESVINC", "CESE", "RENUNC", "EX "]):
        return "DE BAJA"
    if any(k in s for k in ["INACT", "LICEN", "VACAC", "PERMISO", "SUSP", "AUSENT", "MATERN", "MEDICA"]):
        return "INACTIVO"
    return "ACTIVO"

def extraer_jornada_contrato_estricta(val):
    if pd.isna(val):
        return None
    if isinstance(val, (int, float)):
        n = int(round(float(val)))
        if n in [18, 20, 22, 24, 25, 30, 36, 40, 42, 44, 45]:
            return 30 if n <= 32 else 42
        return None

    s = str(val).strip().upper()
    if not s or s in ["NAN", "NONE"]:
        return None

    if ":" in s or "/" in s or re.search(r'\d+\s*-\s*\d+', s):
        return None

    s_clean = s.replace("HORAS", "").replace("HRS", "").replace("HR", "").replace("H", "").strip()
    try:
        n = int(round(float(s_clean.replace(",", "."))))
        if n in [18, 20, 22, 24, 25, 30, 36, 40, 42, 44, 45]:
            return 30 if n <= 32 else 42
    except:
        pass

    if any(k in s for k in ["PART TIME", "PART-TIME", "PT 30", "30 HRS", "30 HORAS"]):
        return 30
    if any(k in s for k in ["FULL TIME", "FULL-TIME", "FT 42", "42 HRS", "42 HORAS", "44 HRS", "45 HRS"]):
        return 42

    return None

def a_segundos(val):
    if pd.isna(val) or val == "": return 0
    if isinstance(val, (int, float)): return int(val)
    s = str(val).strip()
    if ":" in s:
        partes = s.split(":")
        if len(partes) == 3: return int(partes[0]) * 3600 + int(partes[1]) * 60 + int(partes[2])
        elif len(partes) == 2: return int(partes[0]) * 60 + int(partes[1])
    try: return int(float(s))
    except: return 0

def formatear_segundos(segundos):
    if pd.isna(segundos): return "00:00:00"
    segundos = max(0, int(segundos))
    h = segundos // 3600
    m = (segundos % 3600) // 60
    s = segundos % 60
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"

def formato_clp(val):
    try: return f"${int(round(val)):,}".replace(",", ".")
    except: return "$0"

def limpiar_monto_clp(val):
    try:
        return float(str(val).replace('$', '').replace('.', '').replace(',', '').strip())
    except:
        return 0.0

def highlight_estados(val):
    if val == 'ACTIVO': return 'background-color: #059669; color: white; font-weight: bold;'
    elif val == 'INACTIVO': return 'background-color: #D97706; color: white; font-weight: bold;'
    elif val == 'DE BAJA': return 'background-color: #DC2626; color: white; font-weight: bold;'
    return 'background-color: #059669; color: white; font-weight: bold;' 

def highlight_tmo_string(val):
    try:
        secs = a_segundos(val)
        if secs > 600: return 'background-color: rgba(239, 68, 68, 0.25); color: #EF4444; font-weight: bold;'
        elif secs > 432: return 'background-color: rgba(245, 158, 11, 0.2); color: #F59E0B; font-weight: bold;'
        else: return 'color: #10B981; font-weight: bold;'
    except: return ''

def highlight_ocupacion(val):
    try:
        num = float(str(val).replace('%', ''))
        if num >= 65.0: return 'color: #10B981; font-weight: bold;'
        elif num >= 55.0: return 'color: #F59E0B; font-weight: bold;'
        else: return 'color: #EF4444; font-weight: bold;'
    except: return ''

def highlight_cumpl_turno(val):
    try:
        num = float(str(val).replace('%', ''))
        if num >= 85.0: return 'color: #10B981; font-weight: bold;'
        elif num >= 75.0: return 'color: #F59E0B; font-weight: bold;'
        else: return 'color: #EF4444; font-weight: bold;'
    except: return ''

# ==============================================================================
# ESTILOS CSS INYECTADOS (MODO EJECUTIVO / GERENCIA: TEXTO Y CAJAS GRANDES)
# ==============================================================================
def inyectar_estilos():
    st.markdown("""
    <style>
        .card-prod {
            background: linear-gradient(145deg, #1E1B4B 0%, #312E81 100%);
            border: 2px solid #4F46E5;
            border-radius: 16px;
            padding: 26px 24px;
            margin-top: 8px;
            margin-bottom: 22px;
            min-height: 148px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            box-shadow: 0 10px 24px rgba(0, 0, 0, 0.45);
        }
        .card-prod-title {
            font-size: 1.05rem;
            color: #E0E7FF;
            text-transform: uppercase;
            font-weight: 800;
            letter-spacing: 0.6px;
            margin-bottom: 10px;
        }
        .card-prod-value {
            font-size: 2.55rem;
            font-weight: 900;
            line-height: 1.15;
            letter-spacing: -0.5px;
        }
        .card-prod-sub {
            font-size: 1.35rem;
            font-weight: 700;
            opacity: 0.95;
        }

        .filter-badge-bar {
            display: grid;
            grid-template-columns: repeat(6, 1fr);
            gap: 14px;
            margin-bottom: 24px;
        }
        @media (max-width: 1200px) {
            .filter-badge-bar { grid-template-columns: repeat(3, 1fr); }
        }
        .f-badge {
            background: linear-gradient(145deg, #131D31 0%, #1E293B 100%);
            border: 2px solid #334155;
            border-radius: 14px;
            padding: 16px 14px;
            text-align: center;
            box-shadow: 0 6px 14px rgba(0, 0, 0, 0.35);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 98px;
        }
        .f-badge-label {
            font-size: 0.92rem;
            color: #CBD5E1;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 6px;
        }
        .f-badge-num {
            font-size: 2.05rem;
            font-weight: 900;
            line-height: 1.1;
        }

        .card-alert {
            background: linear-gradient(145deg, #450A0A 0%, #7F1D1D 100%);
            border: 2px solid #EF4444;
            border-radius: 16px;
            padding: 22px 26px;
            margin-bottom: 18px;
        }

        div[data-testid="stSelectbox"] label p,
        div[data-testid="stNumberInput"] label p {
            font-size: 0.98rem !important;
            font-weight: 700 !important;
            color: #F1F5F9 !important;
        }
        
        [data-testid="stDataFrame"] table thead tr th {
            background-color: #1E3A8A !important;
            color: #F8FAFC !important;
            font-weight: bold !important;
            font-size: 0.95rem !important;
            text-transform: uppercase !important;
            border-bottom: 2px solid #3B82F6 !important;
        }
    </style>
    """, unsafe_allow_html=True)

# ==============================================================================
# MOTOR ESTRICTO DE SINCRONIZACIÓN DE ESTADOS Y JORNADA DESDE BASE MAESTRA
# ==============================================================================
def _procesar_df_maestra_estricto(df_m, maestra_dict):
    if df_m is None or not isinstance(df_m, pd.DataFrame) or df_m.empty:
        return

    df_work = df_m.copy()
    cols_str = [str(c).upper() for c in df_work.columns]
    if any("UNNAMED" in c for c in cols_str):
        for idx_r in range(min(10, len(df_work))):
            row_vals = [str(x).upper().strip() for x in df_work.iloc[idx_r].values]
            if any(any(k in rv for k in ["NOMBRE", "EJECUTIVO", "AGENTE", "EAC"]) for rv in row_vals):
                df_work.columns = [str(x).strip() for x in df_work.iloc[idx_r].values]
                df_work = df_work.iloc[idx_r + 1:].copy()
                break

    df_work.columns = [str(c).lower().strip() for c in df_work.columns]

    col_nom = next((c for c in df_work.columns if c in [
        'nombre eac', 'ejecutivo', 'nombre', 'nombre completo', 'agente', 'nombres', 'nombre_eac', 'nombre_ejecutivo'
    ]), None)
    if not col_nom:
        col_nom = next((c for c in df_work.columns if 'nombre' in c or 'ejecutivo' in c or 'eac' in c), None)

    col_est = next((c for c in df_work.columns if c in [
        'estado bbdd', 'estado', 'status', 'estado_bbdd', 'estado_ejecutivo', 'vigencia'
    ]), None)
    if not col_est:
        col_est = next((c for c in df_work.columns if 'estado' in c or 'status' in c), None)

    col_jor = next((c for c in df_work.columns if c in [
        'hrs de contrato', 'jornada', 'horas', 'horas semanales', 'contrato',
        'hrs_de_contrato', 'hrs contrato', 'hrs_contrato', 'horas_contrato', 'horas de contrato', 'jornada_hrs'
    ]), None)
    if not col_jor:
        col_jor = next((c for c in df_work.columns if ('contrato' in c or 'jornada' in c or 'semanal' in c) and 'inicio' not in c and 'fin' not in c and 'fecha' not in c), None)

    if not col_nom:
        return

    for _, row in df_work.iterrows():
        raw_nom = str(row[col_nom]).strip() if pd.notna(row[col_nom]) else ""
        nom_exact = re.sub(r'\s+', ' ', raw_nom.upper())
        nom_norm = normalizar_texto_nombre(raw_nom)
        if not nom_norm or nom_norm in ["NAN", "NONE", "TOTAL"]:
            continue

        estado = normalizar_estado_agente(row[col_est]) if (col_est and pd.notna(row[col_est])) else "ACTIVO"
        jornada_val = extraer_jornada_contrato_estricta(row[col_jor]) if (col_jor and pd.notna(row[col_jor])) else None

        for key_name in set([nom_exact, nom_norm]):
            if not key_name:
                continue
            prev = maestra_dict.get(key_name)
            if prev is None:
                maestra_dict[key_name] = {
                    'estado': estado,
                    'jornada': jornada_val if jornada_val is not None else 42,
                    'tiene_jornada': jornada_val is not None
                }
            else:
                if jornada_val is not None and not prev.get('tiene_jornada', False):
                    prev['jornada'] = jornada_val
                    prev['tiene_jornada'] = True
                if estado != "ACTIVO" and prev.get('estado') == "ACTIVO":
                    prev['estado'] = estado

@st.cache_data(show_spinner=False, max_entries=4)
def obtener_datos_maestros(_con, _hojas_semanales, version_datos):
    maestra_dict = {}
    
    try:
        if _hojas_semanales and isinstance(_hojas_semanales, dict):
            for k, v in _hojas_semanales.items():
                if any(kw in str(k).upper() for kw in ["BBDD", "BDD", "CLIENTE FINAL", "MAESTRO", "EJECUTIVOS", "DOTACION"]) and isinstance(v, pd.DataFrame) and not v.empty:
                    _procesar_df_maestra_estricto(v, maestra_dict)
    except Exception:
        pass

    if _con is not None:
        try:
            tablas_db = [r[0] for r in _con.execute("SHOW TABLES").fetchall()]
            tablas_maestras = [t for t in tablas_db if any(k in t.lower() for k in ["maestro", "bdd", "bbdd", "ejecutivo", "personal"])]
            for tb in tablas_maestras:
                try:
                    df_tb = _con.execute(f"SELECT * FROM {tb}").df()
                    _procesar_df_maestra_estricto(df_tb, maestra_dict)
                except Exception:
                    pass
        except Exception:
            pass

    return maestra_dict

def buscar_agente_en_maestra(nombre_agente, dict_maestra, indice_tokens):
    if not dict_maestra:
        return None
    nom_up = re.sub(r'\s+', ' ', str(nombre_agente).strip().upper())
    if nom_up in dict_maestra:
        return dict_maestra[nom_up]

    nom_norm = normalizar_texto_nombre(nombre_agente)
    if nom_norm in dict_maestra:
        return dict_maestra[nom_norm]

    tokens_ag = set(nom_norm.split())
    if len(tokens_ag) >= 2:
        clave_sorted = " ".join(sorted(tokens_ag))
        if clave_sorted in indice_tokens:
            return indice_tokens[clave_sorted]

    return None

# ==============================================================================
# MOTOR DE PROCESAMIENTO WFM
# ==============================================================================
@st.cache_data(show_spinner=False, max_entries=3)
def procesar_datos_productividad(_df_raw, _dict_maestra, fecha_activa_str, filas_raw, version_datos):
    df_bp = _df_raw.copy()
    dict_maestra = _dict_maestra or {}
    df_bp.columns = [str(c).lower().strip() for c in df_bp.columns]

    if 'first_name' in df_bp.columns and 'last_name' in df_bp.columns:
        df_bp['Agente_Limpio'] = (df_bp['first_name'].astype(str).str.strip() + ' ' + df_bp['last_name'].astype(str).str.strip()).str.upper()
        df_bp['Agente_Limpio'] = df_bp['Agente_Limpio'].replace(r'\s+', ' ', regex=True)
        
        df_bp['Fecha_Obj'] = pd.to_datetime(df_bp['start_time'], errors='coerce', dayfirst=True)
        df_bp = df_bp.dropna(subset=['Fecha_Obj'])
        df_bp['Fecha_Corta'] = df_bp['Fecha_Obj'].dt.strftime('%Y-%m-%d')
        df_bp['Mes'] = df_bp['Fecha_Obj'].dt.strftime('%Y-%m')
        df_bp['Hora_Str'] = df_bp['Fecha_Obj'].dt.strftime('%H:%M')
        
        def extraer_seg(columna):
            return df_bp[columna].apply(a_segundos) if columna in df_bp.columns else pd.Series(0, index=df_bp.index)

        if 'activity' in df_bp.columns:
            df_bp['Es_Llamada'] = df_bp['activity'].astype(str).str.strip().str.upper().isin(['INBOUND_CALL', 'OUTBOUND_CALL', 'CALL']).astype(int)
        else:
            df_bp['Es_Llamada'] = 1

        df_bp['Conexion_Seg'] = extraer_seg('duration')
        
        talk = extraer_seg('talk_time')
        hold = extraer_seg('hold_time')
        acw = extraer_seg('after_call_work_time')
        if acw.sum() == 0: acw = extraer_seg('acw_time')

        df_bp['TMO_Segundos'] = (talk + hold + acw) * df_bp['Es_Llamada']
        df_bp['Cant_Llamadas'] = ((df_bp['Es_Llamada'] == 1) & (df_bp['TMO_Segundos'] > 0)).astype(int)
        
        df_bp['Area'] = df_bp['team_name'].astype(str).str.strip().str.upper() if 'team_name' in df_bp.columns else "GENERAL"
        
        agentes_unicos = df_bp['Agente_Limpio'].unique()
        indice_tokens = {" ".join(sorted(normalizar_texto_nombre(k).split())): v for k, v in dict_maestra.items() if normalizar_texto_nombre(k)}
        
        mapa_estado = {}
        mapa_jornada = {}

        for ag in agentes_unicos:
            match = buscar_agente_en_maestra(ag, dict_maestra, indice_tokens)
            if match:
                mapa_estado[ag] = normalizar_estado_agente(match.get('estado', 'ACTIVO'))
                mapa_jornada[ag] = int(match.get('jornada', 42))
            else:
                mapa_estado[ag] = 'ACTIVO'
                mapa_jornada[ag] = 42

        df_bp['Estado'] = df_bp['Agente_Limpio'].map(mapa_estado).fillna('ACTIVO')
        df_bp['Jornada_Hrs'] = df_bp['Agente_Limpio'].map(mapa_jornada).fillna(42).astype(int)
        
        return df_bp, "OK"
    else:
        return pd.DataFrame(), "El archivo no tiene la estructura esperada de Bright Pattern V2."

# ==============================================================================
# EXPORTADOR EXCEL EJECUTIVO SOBRE FONDO BLANCO (CON TÍTULOS AZULES Y SEMÁFOROS)
# ==============================================================================
@st.cache_data(show_spinner=False, max_entries=8)
def generar_excel_consola_visual(_df_tabla, nombre_hoja, titulo_reporte, factor_mes, firma_cache):
    df_tabla = _df_tabla.copy()
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_tabla.to_excel(writer, sheet_name=nombre_hoja, index=False, startrow=2)
        ws = writer.sheets[nombre_hoja]
        
        from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        max_col = len(df_tabla.columns)
        max_row = ws.max_row

        # Paleta Ejecutiva de Fondo Blanco con Encabezados Corporativos y Semáforos Nítidos
        title_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
        header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        alert_header_fill = PatternFill(start_color="991B1B", end_color="991B1B", fill_type="solid")
        zebra_even = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
        zebra_odd = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

        # Fills de Estado Sólidos y Semáforos Pastel sobre Fondo Claro
        fill_activo = PatternFill(start_color="059669", end_color="059669", fill_type="solid")
        fill_inactivo = PatternFill(start_color="D97706", end_color="D97706", fill_type="solid")
        fill_baja = PatternFill(start_color="DC2626", end_color="DC2626", fill_type="solid")
        fill_rojo_soft = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
        fill_amarillo_soft = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
        fill_verde_soft = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")

        # Fuentes adaptadas para máxima legibilidad en fondo blanco
        title_font = Font(color="1E3A8A", bold=True, name="Segoe UI", size=13)
        header_font = Font(color="FFFFFF", bold=True, name="Segoe UI", size=10)
        base_font = Font(color="0F172A", bold=False, name="Segoe UI", size=10)
        bold_white = Font(color="FFFFFF", bold=True, name="Segoe UI", size=10)
        font_verde = Font(color="15803D", bold=True, name="Segoe UI", size=10)
        font_amarillo = Font(color="B45309", bold=True, name="Segoe UI", size=10)
        font_rojo = Font(color="B91C1C", bold=True, name="Segoe UI", size=10)
        font_azul = Font(color="0369A1", bold=True, name="Segoe UI", size=10)
        font_morado = Font(color="7E22CE", bold=True, name="Segoe UI", size=10)
        font_gris = Font(color="475569", bold=False, name="Segoe UI", size=10)

        thin_border = Border(
            left=Side(style='thin', color='CBD5E1'),
            right=Side(style='thin', color='CBD5E1'),
            top=Side(style='thin', color='CBD5E1'),
            bottom=Side(style='thin', color='CBD5E1')
        )

        # Banner superior claro con título corporativo centrado
        ws.merge_cells(start_row=1, start_column=1, end_row=2, end_column=max_col)
        for r_top in range(1, 3):
            for c_top in range(1, max_col + 1):
                c_cell = ws.cell(row=r_top, column=c_top)
                c_cell.fill = title_fill
                c_cell.border = thin_border
        top_cell = ws.cell(row=1, column=1)
        top_cell.value = f"📊 {titulo_reporte.upper()}"
        top_cell.font = title_font
        top_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        ws.row_dimensions[1].height = 20
        ws.row_dimensions[2].height = 18

        # Encabezados de las columnas (Fila 3) en azul corporativo o rojo alerta
        es_tabla_alerta = "ALERTA" in nombre_hoja.upper() or "TMO" in nombre_hoja.upper()
        ws.row_dimensions[3].height = 28
        col_names = list(df_tabla.columns)
        for col_idx in range(1, max_col + 1):
            cell = ws.cell(row=3, column=col_idx)
            cell.fill = alert_header_fill if es_tabla_alerta else header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin_border

        last_col_letter = get_column_letter(max_col)
        ws.auto_filter.ref = f"A3:{last_col_letter}{max_row}"
        ws.freeze_panes = "A4"

        for row_idx in range(4, max_row + 1):
            ws.row_dimensions[row_idx].height = 22
            bg_row = zebra_even if (row_idx % 2 == 0) else zebra_odd

            jor_num = 42.0
            if "Jornada" in col_names:
                c_jor = col_names.index("Jornada") + 1
                val_jor_str = str(ws.cell(row=row_idx, column=c_jor).value or "42").replace("hrs", "").replace("h", "").strip()
                try: jor_num = float(val_jor_str)
                except: jor_num = 42.0

            for col_idx in range(1, max_col + 1):
                col_name = col_names[col_idx - 1]
                cell = ws.cell(row=row_idx, column=col_idx)
                val_str = str(cell.value if cell.value is not None else "").strip()

                cell.fill = bg_row
                cell.font = base_font
                cell.border = thin_border
                cell.alignment = Alignment(
                    horizontal="left" if col_name in ["Ejecutivo", "Area"] else "center",
                    vertical="center"
                )

                # 1. Semáforo Estado
                if col_name == "Estado":
                    if val_str == "ACTIVO":
                        cell.fill = fill_activo
                        cell.font = bold_white
                    elif val_str == "INACTIVO":
                        cell.fill = fill_inactivo
                        cell.font = bold_white
                    elif val_str == "DE BAJA":
                        cell.fill = fill_baja
                        cell.font = bold_white

                # 2. Jornada (30 hrs morado / 42 hrs azul)
                elif col_name == "Jornada":
                    if "30" in val_str:
                        cell.font = font_morado
                    else:
                        cell.font = font_azul

                # 3. Semáforo TMO Promedio / Peor TMO
                elif col_name in ["TMO Promedio", "Peor TMO", "TMO Ponderado"]:
                    secs = a_segundos(val_str)
                    if secs > 600:
                        cell.fill = fill_rojo_soft
                        cell.font = font_rojo
                    elif secs > 432:
                        cell.fill = fill_amarillo_soft
                        cell.font = font_amarillo
                    else:
                        cell.font = font_verde

                # 4. Semáforo Cumplimiento de Turno (%)
                elif col_name == "Cumpl. Turno (%)":
                    try:
                        num = float(val_str.replace('%', '').replace(',', '.'))
                        if num >= 85.0:
                            cell.font = font_verde
                        elif num >= 75.0:
                            cell.fill = fill_amarillo_soft
                            cell.font = font_amarillo
                        else:
                            cell.fill = fill_rojo_soft
                            cell.font = font_rojo
                    except: pass

                # 5. Semáforo Ocupación (%)
                elif col_name == "Ocupación (%)":
                    try:
                        num = float(val_str.replace('%', '').replace(',', '.'))
                        if num >= 65.0:
                            cell.font = font_verde
                        elif num >= 55.0:
                            cell.fill = fill_amarillo_soft
                            cell.font = font_amarillo
                        else:
                            cell.fill = fill_rojo_soft
                            cell.font = font_rojo
                    except: pass

                # 6. Semáforo Rentabilidad Proporcional ($)
                elif col_name == "Rentabilidad ($)":
                    val_rent = limpiar_monto_clp(val_str)
                    f_jor = jor_num / 42.0
                    u_verde = META_MENSUAL_VERDE_42H * f_jor * factor_mes
                    u_amarillo = META_MENSUAL_AMARILLO_42H * f_jor * factor_mes
                    if val_rent < u_amarillo:
                        cell.fill = fill_rojo_soft
                        cell.font = font_rojo
                    elif val_rent < u_verde:
                        cell.fill = fill_amarillo_soft
                        cell.font = font_amarillo
                    else:
                        cell.fill = fill_verde_soft
                        cell.font = font_verde

                # 7. Columnas CPH y Llamadas Atendidas
                elif col_name in ["CPH", "CPH Actual (Productividad)", "Llamadas Atendidas", "Total Atendidas"]:
                    cell.font = font_azul

                # 8. Columnas Críticas en pestaña TMO
                elif col_name in ["Veces > 10 Min", "% Llamadas Críticas"]:
                    cell.fill = fill_rojo_soft
                    cell.font = font_rojo

                # 9. Meta Proporcional
                elif col_name == "Meta Prop. ($)":
                    cell.font = font_gris

        for col_idx in range(1, max_col + 1):
            col_letter = get_column_letter(col_idx)
            col_header = str(ws.cell(row=3, column=col_idx).value or "")
            max_len = len(col_header)
            for r_idx in range(4, min(max_row + 1, 300)):
                v = ws.cell(row=r_idx, column=col_idx).value
                if v is not None:
                    max_len = max(max_len, len(str(v)))
            ws.column_dimensions[col_letter].width = max(max_len + 5, 14)

    return output.getvalue()

# ==============================================================================
# MÓDULO PRINCIPAL DE RENDERIZADO
# ==============================================================================
def renderizar_modulo_productividad(con, fecha_activa_str):
    inyectar_estilos()
    
    st.markdown(f"""
        <div style="background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%); border: 1px solid #334155; border-radius: 14px; padding: 18px 24px; margin-bottom: 22px;">
            <div style="font-size: 1.85rem; font-weight: 900; color: #F8FAFC;">
                📈 Inteligencia de Productividad y Conexión WFM
            </div>
            <div style="font-size: 0.98rem; color: #CBD5E1; margin-top: 4px;">
                Control de Horas, Ocupación (Cruce Jornada y Días Trabajados), CPH y Rentabilidad Proporcional para el <b>{fecha_activa_str}</b>.
            </div>
        </div>
    """, unsafe_allow_html=True)

    try:
        df_raw = con.execute(f"SELECT * FROM datos_productividad_tmo WHERE fecha_gestion = '{fecha_activa_str}'").df()
    except Exception:
        df_raw = pd.DataFrame()

    if df_raw.empty:
        st.warning(f"⚠️ No hay datos de Productividad cargados para el {fecha_activa_str}. Ve a la pestaña 'Ingesta de Datos' y sube el archivo 'Agent Activity'.")
        return

    version_datos = st.session_state.get("version_datos", 1)
    hojas_semanales = st.session_state.get("excel_colaciones_hojas", {})
    
    maestra_cruzada = obtener_datos_maestros(con, hojas_semanales, version_datos)
    df_bp, status = procesar_datos_productividad(df_raw, maestra_cruzada, fecha_activa_str, len(df_raw), version_datos)
        
    if status != "OK":
        st.error(status)
        return

    df_agentes_base = df_bp.groupby("Agente_Limpio").agg(
        Estado=('Estado', 'first'),
        Jornada_Hrs=('Jornada_Hrs', 'first'),
        Area=('Area', 'first')
    ).reset_index()

    cnt_jor = df_agentes_base["Jornada_Hrs"].value_counts().to_dict()
    cnt_42 = int(cnt_jor.get(42, 0))
    cnt_30 = int(cnt_jor.get(30, 0))
    cnt_tot_ag = len(df_agentes_base)

    cnt_est = df_agentes_base["Estado"].value_counts().to_dict()
    cnt_act = int(cnt_est.get("ACTIVO", 0))
    cnt_ina = int(cnt_est.get("INACTIVO", 0))
    cnt_baj = int(cnt_est.get("DE BAJA", 0))

    st.markdown(f"""
    <div class="filter-badge-bar">
        <div class="f-badge">
            <div class="f-badge-label">👥 Total Ejecutivos</div>
            <div class="f-badge-num" style="color:#F8FAFC;">{cnt_tot_ag}</div>
        </div>
        <div class="f-badge" style="border-color:#0284C7;">
            <div class="f-badge-label">🔵 Contrato 42 hrs</div>
            <div class="f-badge-num" style="color:#38BDF8;">{cnt_42}</div>
        </div>
        <div class="f-badge" style="border-color:#9333EA;">
            <div class="f-badge-label">🟣 Contrato 30 hrs</div>
            <div class="f-badge-num" style="color:#C084FC;">{cnt_30}</div>
        </div>
        <div class="f-badge" style="border-color:#059669;">
            <div class="f-badge-label">🟢 Activos</div>
            <div class="f-badge-num" style="color:#10B981;">{cnt_act}</div>
        </div>
        <div class="f-badge" style="border-color:#D97706;">
            <div class="f-badge-label">🟠 Inactivos</div>
            <div class="f-badge-num" style="color:#F59E0B;">{cnt_ina}</div>
        </div>
        <div class="f-badge" style="border-color:#DC2626;">
            <div class="f-badge-label">🔴 De Baja</div>
            <div class="f-badge-num" style="color:#EF4444;">{cnt_baj}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ==========================================================================
    # BARRA DE FILTROS MAESTROS
    # ==========================================================================
    st.markdown("### 🔎 Filtros de Segmentación WFM")
    c_f1, c_f2, c_f3, c_f4 = st.columns(4)
    c_f_est, c_f_jor, c_f5, c_f7 = st.columns([1.15, 1.15, 1.2, 0.8])
    
    meses_disp = ["TODOS"] + sorted(df_bp["Mes"].dropna().unique().tolist())
    mes_sel = c_f1.selectbox("📅 Mes:", meses_disp)
    
    fechas_disp = ["TODAS"] + sorted(df_bp[df_bp["Mes"] == mes_sel]["Fecha_Corta"].dropna().unique().tolist() if mes_sel != "TODOS" else df_bp["Fecha_Corta"].dropna().unique().tolist())
    fecha_sel = c_f2.selectbox("📆 Día:", fechas_disp)
    
    horas_disp = ["TODAS"] + sorted(df_bp["Hora_Str"].dropna().unique().tolist())
    hora_sel = c_f3.selectbox("⏰ Tramo Horario:", horas_disp)
    
    areas_disp = ["TODAS"] + sorted(df_bp["Area"].unique().tolist())
    default_area = "AA_FRONT" if "AA_FRONT" in areas_disp else "TODAS"
    area_sel = c_f4.selectbox("🏢 Equipo / Área:", areas_disp, index=areas_disp.index(default_area) if default_area in areas_disp else 0)

    mapa_opciones_estado = {
        f"TODO ({cnt_tot_ag})": "TODO",
        f"ACTIVO ({cnt_act})": "ACTIVO",
        f"INACTIVO ({cnt_ina})": "INACTIVO",
        f"DE BAJA ({cnt_baj})": "DE BAJA"
    }
    estado_lbl_sel = c_f_est.selectbox("🏷️ Estado (Activo / Inactivo / Baja):", list(mapa_opciones_estado.keys()))
    estado_sel = mapa_opciones_estado[estado_lbl_sel]

    mapa_opciones_jornada = {
        f"TODO ({cnt_tot_ag})": "TODO",
        f"42 hrs ({cnt_42})": 42,
        f"30 hrs ({cnt_30})": 30
    }
    jornada_lbl_sel = c_f_jor.selectbox("⏱️ Jornada (42 hrs / 30 hrs / Todo):", list(mapa_opciones_jornada.keys()))
    jornada_sel = mapa_opciones_jornada[jornada_lbl_sel]

    df_ag_disp = df_bp.copy()
    if area_sel != "TODAS":
        df_ag_disp = df_ag_disp[df_ag_disp["Area"] == area_sel]
    if estado_sel != "TODO":
        df_ag_disp = df_ag_disp[df_ag_disp["Estado"] == estado_sel]
    if jornada_sel != "TODO":
        df_ag_disp = df_ag_disp[df_ag_disp["Jornada_Hrs"] == int(jornada_sel)]

    agentes_disp = ["TODOS"] + sorted(df_ag_disp["Agente_Limpio"].unique().tolist())
    agente_sel = c_f5.selectbox("👤 Ejecutivo:", agentes_disp)
    
    umbral_llamadas = c_f7.number_input("📉 Mín. Llamadas:", min_value=0, value=10, help="Filtra cuentas administrativas o pruebas.")

    df_filtro = df_bp.copy()
    if mes_sel != "TODOS": df_filtro = df_filtro[df_filtro["Mes"] == mes_sel]
    if fecha_sel != "TODAS": df_filtro = df_filtro[df_filtro["Fecha_Corta"] == fecha_sel]
    if hora_sel != "TODAS": df_filtro = df_filtro[df_filtro["Hora_Str"] == hora_sel]
    if area_sel != "TODAS": df_filtro = df_filtro[df_filtro["Area"] == area_sel]
    if estado_sel != "TODO": df_filtro = df_filtro[df_filtro["Estado"] == estado_sel]
    if jornada_sel != "TODO": df_filtro = df_filtro[df_filtro["Jornada_Hrs"] == int(jornada_sel)]
    
    if agente_sel != "TODOS": 
        df_filtro = df_filtro[df_filtro["Agente_Limpio"] == agente_sel]
        umbral_llamadas = 0

    if df_filtro.empty:
        st.warning("⚠️ No se encontraron registros para la combinación de Estado, Jornada y Filtros seleccionada.")
        return

    # ==========================================================================
    # CÁLCULOS GLOBALES Y MEGA-TARJETAS PARA GERENCIA
    # ==========================================================================
    df_llamadas = df_filtro[df_filtro["Es_Llamada"] == 1]
    
    dias_informe = max(1, int(df_bp[df_bp["Fecha_Corta"].isin(df_filtro["Fecha_Corta"].unique())]["Fecha_Corta"].nunique()))
    factor_mes = min(1.0, dias_informe / float(DIAS_HABILES_MES_BASE))

    tot_llamadas = int(df_llamadas["Cant_Llamadas"].sum())
    tot_conexion_seg = int(df_filtro["Conexion_Seg"].sum())
    tot_operativo_seg = int(df_llamadas["TMO_Segundos"].sum()) 
    
    tmo_promedio_gral = tot_operativo_seg / tot_llamadas if tot_llamadas > 0 else 0
    cph_gral = tot_llamadas / (tot_conexion_seg / 3600) if tot_conexion_seg > 0 else 0
    rentabilidad_gral = tot_llamadas * VALOR_POR_LLAMADA

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f"""
    <div class="card-prod">
        <div class="card-prod-title">⏱️ Horas de Conexión ({dias_informe} Días)</div>
        <div class="card-prod-value" style="color: #34D399;">{formatear_segundos(tot_conexion_seg)}</div>
    </div>
    """, unsafe_allow_html=True)
    c2.markdown(f"""
    <div class="card-prod">
        <div class="card-prod-title">📞 Llamadas vs CPH Global</div>
        <div class="card-prod-value" style="color: #818CF8;">{tot_llamadas:,} <span class="card-prod-sub">({cph_gral:.1f}/hr)</span></div>
    </div>
    """, unsafe_allow_html=True)
    c3.markdown(f"""
    <div class="card-prod">
        <div class="card-prod-title">💰 Valor Generado</div>
        <div class="card-prod-value" style="color: #C084FC;">{formato_clp(rentabilidad_gral)}</div>
    </div>
    """, unsafe_allow_html=True)
    c4.markdown(f"""
    <div class="card-prod">
        <div class="card-prod-title">⚖️ TMO Ponderado</div>
        <div class="card-prod-value" style="color: #FBBF24;">{formatear_segundos(tmo_promedio_gral)}</div>
    </div>
    """, unsafe_allow_html=True)

    # ==========================================================================
    # AGRUPACIÓN POR EJECUTIVO: CRUCE JORNADA (30H/42H), DÍAS, OCUPACIÓN Y META
    # ==========================================================================
    df_agrupado_completo = df_filtro.groupby(["Agente_Limpio"]).agg(
        Area=('Area', lambda x: ', '.join(sorted(set(x)))),
        Estado=('Estado', 'first'),
        Jornada_Hrs=('Jornada_Hrs', 'first'),
        Dias_Trabajados=('Fecha_Corta', 'nunique'),
        Horas_Conexion_Seg=('Conexion_Seg', 'sum'),
        Total_Llamadas=('Cant_Llamadas', 'sum'),
        Tiempo_Operativo_Seg=('TMO_Segundos', 'sum')
    ).reset_index()

    df_agrupado_completo["Horas_Turno_Dia_Seg"] = (df_agrupado_completo["Jornada_Hrs"] / 5.0) * 3600.0
    df_agrupado_completo["Turno_Esperado_Seg"] = df_agrupado_completo["Dias_Trabajados"] * df_agrupado_completo["Horas_Turno_Dia_Seg"]

    df_agrupado_completo["Cumpl_Turno_%"] = df_agrupado_completo.apply(
        lambda r: (r["Horas_Conexion_Seg"] / r["Turno_Esperado_Seg"] * 100.0) if r["Turno_Esperado_Seg"] > 0 else 0.0, axis=1
    )

    df_agrupado_completo["Base_Ocupacion_Seg"] = df_agrupado_completo[["Horas_Conexion_Seg", "Turno_Esperado_Seg"]].max(axis=1)
    df_agrupado_completo["Ocupacion_%"] = df_agrupado_completo.apply(
        lambda r: min(100.0, (r["Tiempo_Operativo_Seg"] / r["Base_Ocupacion_Seg"] * 100.0)) if r["Base_Ocupacion_Seg"] > 0 else 0.0, axis=1
    )

    df_agrupado_completo["TMO_Promedio_Seg"] = df_agrupado_completo.apply(
        lambda row: row["Tiempo_Operativo_Seg"] / row["Total_Llamadas"] if row["Total_Llamadas"] > 0 else 0, axis=1
    )
    df_agrupado_completo["CPH"] = df_agrupado_completo.apply(
        lambda row: row["Total_Llamadas"] / (row["Horas_Conexion_Seg"] / 3600) if row["Horas_Conexion_Seg"] > 0 else 0, axis=1
    )
    df_agrupado_completo["Rentabilidad"] = df_agrupado_completo["Total_Llamadas"] * VALOR_POR_LLAMADA

    df_agrupado_completo["Factor_Jornada"] = df_agrupado_completo["Jornada_Hrs"] / 42.0
    df_agrupado_completo["Meta_Verde_Prop"] = META_MENSUAL_VERDE_42H * df_agrupado_completo["Factor_Jornada"] * factor_mes
    df_agrupado_completo["Meta_Amarillo_Prop"] = META_MENSUAL_AMARILLO_42H * df_agrupado_completo["Factor_Jornada"] * factor_mes

    df_agrupado = df_agrupado_completo[df_agrupado_completo["Total_Llamadas"] >= umbral_llamadas].copy()
    
    firma_filtro = f"{fecha_activa_str}_{mes_sel}_{fecha_sel}_{hora_sel}_{jornada_sel}_{area_sel}_{agente_sel}_{estado_sel}_{umbral_llamadas}_{len(df_filtro)}_{version_datos}"

    def highlight_jornada(val):
        s = str(val)
        if "30" in s:
            return 'color: #C084FC; font-weight: bold;'
        return 'color: #38BDF8; font-weight: bold;'

    def style_rentabilidad_proporcional(row):
        styles = [''] * len(row)
        if 'Rentabilidad ($)' not in row.index:
            return styles
        idx_rent = row.index.get_loc('Rentabilidad ($)')
        val_rent = limpiar_monto_clp(row['Rentabilidad ($)'])
        
        jor_str = str(row.get('Jornada', '42 hrs')).replace('hrs', '').replace('h', '').strip()
        try:
            jor_num = float(jor_str)
        except:
            jor_num = 42.0
            
        f_jor = jor_num / 42.0
        umbral_verde = META_MENSUAL_VERDE_42H * f_jor * factor_mes
        umbral_amarillo = META_MENSUAL_AMARILLO_42H * f_jor * factor_mes
        
        if val_rent < umbral_amarillo:
            styles[idx_rent] = 'background-color: rgba(239, 68, 68, 0.25); color: #EF4444; font-weight: bold;'
        elif val_rent < umbral_verde:
            styles[idx_rent] = 'background-color: rgba(245, 158, 11, 0.2); color: #F59E0B; font-weight: bold;'
        else:
            styles[idx_rent] = 'color: #10B981; font-weight: bold;'
        return styles

    # ==========================================================================
    # PESTAÑAS CON EXPORTACIÓN VISUAL INDIVIDUAL EN CADA VISTA
    # ==========================================================================
    t_rank, t_ejec, t_tmo, t_graf = st.tabs([
        "🏆 Ranking Productividad", 
        "👤 Panel de Producción y Valores", 
        "🚨 Control de Alertas TMO",
        "📈 Gráfico de Producción"
    ])

    with t_rank:
        c_tit_r, c_btn_r = st.columns([2.2, 1.2])
        c_tit_r.markdown("#### 🏆 Ranking de Productividad y Rentabilidad Proporcional")
        
        df_mostrar_rank = df_agrupado[[
            "Agente_Limpio", "Area", "Estado", "Jornada_Hrs", "Dias_Trabajados",
            "Total_Llamadas", "CPH", "Rentabilidad", "Meta_Verde_Prop", "TMO_Promedio_Seg"
        ]].sort_values(by="Rentabilidad", ascending=False).copy()
        
        df_mostrar_rank["Jornada"] = df_mostrar_rank["Jornada_Hrs"].astype(str) + " hrs"
        df_mostrar_rank["CPH"] = df_mostrar_rank["CPH"].apply(lambda x: f"{x:.1f}")
        df_mostrar_rank["Rentabilidad ($)"] = df_mostrar_rank["Rentabilidad"].apply(formato_clp)
        df_mostrar_rank["Meta Prop. ($)"] = df_mostrar_rank["Meta_Verde_Prop"].apply(formato_clp)
        df_mostrar_rank["TMO Promedio"] = df_mostrar_rank["TMO_Promedio_Seg"].apply(formatear_segundos)
        
        df_mostrar_rank = df_mostrar_rank[[
            "Estado", "Area", "Agente_Limpio", "Jornada", "Dias_Trabajados",
            "Total_Llamadas", "CPH", "Rentabilidad ($)", "Meta Prop. ($)", "TMO Promedio"
        ]].rename(columns={
            "Total_Llamadas": "Llamadas Atendidas",
            "Agente_Limpio": "Ejecutivo",
            "Dias_Trabajados": "Días Trab."
        })

        excel_rank_visual = generar_excel_consola_visual(
            df_mostrar_rank,
            "Ranking_Productividad",
            f"Ranking de Productividad y Rentabilidad ({dias_informe} Días) - {fecha_activa_str}",
            factor_mes,
            f"rank_vis_bl_{firma_filtro}"
        )
        c_btn_r.download_button(
            label="📥 Exportar Ranking Visual (Excel)",
            data=excel_rank_visual,
            file_name=f"Ranking_Productividad_WFM_{fecha_activa_str}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        
        styled_rank = df_mostrar_rank.style\
            .map(highlight_estados, subset=['Estado']) \
            .map(highlight_jornada, subset=['Jornada']) \
            .map(highlight_tmo_string, subset=['TMO Promedio']) \
            .map(lambda _: 'color: #38BDF8; font-weight: bold;', subset=['CPH']) \
            .map(lambda _: 'color: #94A3B8;', subset=['Meta Prop. ($)']) \
            .apply(style_rentabilidad_proporcional, axis=1) \
            .set_table_styles([
                {'selector': 'th', 'props': [('background-color', '#1E3A8A'), ('color', '#F8FAFC'), ('font-weight', 'bold'), ('text-transform', 'uppercase')]},
                {'selector': 'td', 'props': [('border-bottom', '1px solid #334155'), ('text-align', 'center')]}
            ])
            
        st.dataframe(styled_rank, use_container_width=True, hide_index=True)

    with t_ejec:
        c_tit_e, c_btn_e = st.columns([2.2, 1.2])
        c_tit_e.markdown("#### 📊 Producción, Rentabilidad Proporcional, Balance de Turno y Ocupación")

        st.markdown("""
        <div style="background-color: rgba(30, 58, 138, 0.35); border: 1px solid #3B82F6; border-radius: 10px; padding: 14px 18px; margin-bottom: 16px; font-size: 0.96rem; color: #E2E8F0; line-height: 1.6;">
            💡 <b>¿Qué analiza este panel?</b><br>
            • <b>Rentabilidad Proporcional:</b> Evalúa la producción de cada ejecutivo de acuerdo con los días cargados en el reporte y su contrato oficial en Base Maestra (<b style="color:#38BDF8;">42 hrs</b> o <b style="color:#C084FC;">30 hrs</b>), evitando castigar en rojo avances parciales del mes.<br>
            • <b>Cumplimiento de Turno (%):</b> Compara las horas que el ejecutivo estuvo conectado frente a las horas que debía cumplir en los días que asistió. Los valores en <b style="color:#EF4444;">Rojo</b> o <b style="color:#F59E0B;">Amarillo</b> indican menor tiempo de conexión por <b>atrasos, salidas anticipadas o desconexiones prolongadas</b> durante sus jornadas.<br>
            • <b>Ocupación Real (%):</b> Mide qué porcentaje de su jornada estuvo efectivamente hablando y gestionando llamadas.
        </div>
        """, unsafe_allow_html=True)
        
        df_detalle = df_agrupado.sort_values(by="Total_Llamadas", ascending=False).copy()
        
        df_detalle["Jornada"] = df_detalle["Jornada_Hrs"].astype(str) + " hrs"
        df_detalle["Hrs. Turno Esperadas"] = df_detalle["Turno_Esperado_Seg"].apply(formatear_segundos)
        df_detalle["Tpo. Conexión Total"] = df_detalle["Horas_Conexion_Seg"].apply(formatear_segundos)
        df_detalle["Cumpl. Turno (%)"] = df_detalle["Cumpl_Turno_%"].apply(lambda x: f"{x:.1f}%")
        df_detalle["Tpo. Operativo Hablando"] = df_detalle["Tiempo_Operativo_Seg"].apply(formatear_segundos)
        df_detalle["Ocupación (%)"] = df_detalle["Ocupacion_%"].apply(lambda x: f"{x:.1f}%")
        df_detalle["CPH"] = df_detalle["CPH"].apply(lambda x: f"{x:.1f}")
        df_detalle["Rentabilidad ($)"] = df_detalle["Rentabilidad"].apply(formato_clp)
        df_detalle["Meta Prop. ($)"] = df_detalle["Meta_Verde_Prop"].apply(formato_clp)
        df_detalle["TMO Promedio"] = df_detalle["TMO_Promedio_Seg"].apply(formatear_segundos)
        
        df_detalle = df_detalle[[
            "Estado", "Area", "Agente_Limpio", "Jornada", "Dias_Trabajados",
            "Hrs. Turno Esperadas", "Tpo. Conexión Total", "Cumpl. Turno (%)",
            "Tpo. Operativo Hablando", "Total_Llamadas", "CPH", "Ocupación (%)",
            "Rentabilidad ($)", "Meta Prop. ($)", "TMO Promedio"
        ]].rename(columns={
            "Total_Llamadas": "Llamadas Atendidas",
            "Agente_Limpio": "Ejecutivo",
            "Dias_Trabajados": "Días Trab."
        })

        excel_ejec_visual = generar_excel_consola_visual(
            df_detalle,
            "Panel_Produccion_WFM",
            f"Panel de Producción, Turno, Ocupación y Rentabilidad ({dias_informe} Días) - {fecha_activa_str}",
            factor_mes,
            f"ejec_vis_bl_{firma_filtro}"
        )
        c_btn_e.download_button(
            label="📥 Exportar Panel Visual (Excel)",
            data=excel_ejec_visual,
            file_name=f"Panel_Produccion_WFM_{fecha_activa_str}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        
        max_llamadas_detalle = int(df_detalle["Llamadas Atendidas"].max()) if not df_detalle.empty else 1

        styled_detalle = df_detalle.style\
            .map(highlight_estados, subset=['Estado']) \
            .map(highlight_jornada, subset=['Jornada']) \
            .map(highlight_tmo_string, subset=['TMO Promedio']) \
            .map(highlight_cumpl_turno, subset=['Cumpl. Turno (%)']) \
            .map(highlight_ocupacion, subset=['Ocupación (%)']) \
            .map(lambda _: 'color: #94A3B8;', subset=['Meta Prop. ($)']) \
            .apply(style_rentabilidad_proporcional, axis=1) \
            .bar(subset=['Llamadas Atendidas'], color='#3B82F6', vmin=0, vmax=max_llamadas_detalle) \
            .set_table_styles([
                {'selector': 'th', 'props': [('background-color', '#1E3A8A'), ('color', '#F8FAFC'), ('font-weight', 'bold'), ('text-transform', 'uppercase')]},
                {'selector': 'td', 'props': [('border-bottom', '1px solid #334155'), ('text-align', 'center')]}
            ])
            
        st.dataframe(styled_detalle, use_container_width=True, hide_index=True)

    with t_tmo:
        df_rojos = df_llamadas[df_llamadas["TMO_Segundos"] > 600].copy()
        
        st.markdown(f"""
        <div class="card-alert">
            <div style="font-size: 1.05rem; color: #FECACA; text-transform: uppercase; font-weight: 800;">⚠️ Alerta de Impacto en Productividad por TMO Crítico</div>
            <div style="font-size: 2.5rem; font-weight: 900; color: #FCA5A5; margin: 6px 0;">{len(df_rojos):,} llamadas críticas en total</div>
        </div>
        """, unsafe_allow_html=True)
        
        if not df_rojos.empty:
            df_alertas = df_rojos.groupby(["Agente_Limpio"]).agg(
                Veces_Mayor_10Min=('Cant_Llamadas', 'count'),
                Peor_TMO_Seg=('TMO_Segundos', 'max')
            ).reset_index()
            
            df_alertas = df_alertas.merge(df_agrupado_completo[["Agente_Limpio", "Total_Llamadas", "CPH", "Area", "Estado", "Jornada_Hrs"]], on="Agente_Limpio", how="left")
            df_alertas["Jornada"] = df_alertas["Jornada_Hrs"].astype(str) + " hrs"
            df_alertas["% Llamadas Críticas"] = (df_alertas["Veces_Mayor_10Min"] / df_alertas["Total_Llamadas"] * 100).apply(lambda x: f"{x:.1f}%")
            df_alertas["Peor TMO"] = df_alertas["Peor_TMO_Seg"].apply(formatear_segundos)
            df_alertas["CPH Actual (Productividad)"] = df_alertas["CPH"].apply(lambda x: f"{x:.1f}")
            
            df_alertas_show = df_alertas[["Estado", "Area", "Agente_Limpio", "Jornada", "Total_Llamadas", "Veces_Mayor_10Min", "% Llamadas Críticas", "Peor TMO", "CPH Actual (Productividad)"]].sort_values(by="Veces_Mayor_10Min", ascending=False)
            df_alertas_show = df_alertas_show.rename(columns={"Total_Llamadas": "Total Atendidas", "Veces_Mayor_10Min": "Veces > 10 Min", "Agente_Limpio": "Ejecutivo"})
            
            c_cap_tmo, c_btn_tmo = st.columns([2.2, 1.2])
            c_cap_tmo.caption("*(Mostrando incidentes críticos ordenados por impacto. El Excel conserva el formato visual de alerta)*")

            excel_rojos_visual = generar_excel_consola_visual(
                df_alertas_show,
                "Alertas_Impacto_TMO",
                f"Control de Alertas TMO Crítico (>10 Min) - {fecha_activa_str}",
                factor_mes,
                f"rojos_vis_bl_{firma_filtro}"
            )
            c_btn_tmo.download_button(
                label="📥 Exportar Alertas TMO Visual (Excel)",
                data=excel_rojos_visual,
                file_name=f"Alertas_TMO_WFM_{fecha_activa_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

            styled_alertas = df_alertas_show.head(1000).style\
                .map(highlight_estados, subset=['Estado']) \
                .map(highlight_jornada, subset=['Jornada']) \
                .map(lambda _: 'color: #EF4444; font-weight: bold;', subset=['Veces > 10 Min', 'Peor TMO', '% Llamadas Críticas']) \
                .map(lambda _: 'color: #38BDF8; font-weight: bold;', subset=['CPH Actual (Productividad)']) \
                .set_table_styles([
                    {'selector': 'th', 'props': [('background-color', '#7F1D1D'), ('color', '#F8FAFC'), ('font-weight', 'bold'), ('text-transform', 'uppercase')]},
                    {'selector': 'td', 'props': [('border-bottom', '1px solid #334155'), ('text-align', 'center')]}
                ])
                
            st.dataframe(styled_alertas, use_container_width=True, hide_index=True)
        else:
            st.success("🎉 ¡Excelente! Ningún ejecutivo superó los 10 minutos críticos de TMO.")

    with t_graf:
        c_tit_g, c_btn_g = st.columns([2.2, 1.2])
        c_tit_g.markdown(f"#### 📊 Producción General Diaria " + (f"({agente_sel})" if agente_sel != "TODOS" else ""))
        
        df_dia_tendencia = df_llamadas.groupby("Fecha_Corta").agg(
            Llamadas=('Cant_Llamadas', 'sum'),
            Tiempo_Seg=('TMO_Segundos', 'sum')
        ).reset_index()
        df_dia_tendencia["TMO_Promedio"] = df_dia_tendencia.apply(lambda row: row["Tiempo_Seg"] / row["Llamadas"] if row["Llamadas"] > 0 else 0, axis=1)
        df_dia_tendencia = df_dia_tendencia.sort_values(by="Fecha_Corta")

        if not df_dia_tendencia.empty:
            df_export_tendencia = pd.DataFrame({
                "Fecha": df_dia_tendencia["Fecha_Corta"],
                "Llamadas Atendidas": df_dia_tendencia["Llamadas"],
                "Tiempo Operativo": df_dia_tendencia["Tiempo_Seg"].apply(formatear_segundos),
                "TMO Promedio": df_dia_tendencia["TMO_Promedio"].apply(formatear_segundos),
                "Rentabilidad ($)": (df_dia_tendencia["Llamadas"] * VALOR_POR_LLAMADA).apply(formato_clp)
            })
            excel_tend_visual = generar_excel_consola_visual(
                df_export_tendencia,
                "Resumen_Diario_WFM",
                f"Evolución Diaria de Producción y TMO - {fecha_activa_str}",
                factor_mes / max(1, dias_informe),
                f"tend_vis_bl_{firma_filtro}"
            )
            c_btn_g.download_button(
                label="📥 Exportar Resumen Diario Visual (Excel)",
                data=excel_tend_visual,
                file_name=f"Resumen_Diario_Produccion_{fecha_activa_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

        if HAY_PLOTLY and not df_dia_tendencia.empty:
            fig_ev = go.Figure()
            fig_ev.add_trace(go.Bar(x=df_dia_tendencia["Fecha_Corta"], y=df_dia_tendencia["Llamadas"], name="Llamadas Atendidas", marker_color="#0EA5E9", yaxis="y1"))
            fig_ev.add_trace(go.Scatter(x=df_dia_tendencia["Fecha_Corta"], y=df_dia_tendencia["TMO_Promedio"] / 60, name="TMO Ponderado (Min)", mode="lines+markers", line=dict(color="#F43F5E", width=3, shape="spline"), yaxis="y2"))
            fig_ev.add_hline(y=7.2, line_dash="dot", line_color="#10B981", annotation_text="Meta TMO (7.2 min)", annotation_position="top right")
            fig_ev.add_hline(y=10.0, line_dash="dash", line_color="#EF4444", annotation_text="Alerta Roja (10 min)", annotation_position="top left")
            fig_ev.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), xaxis=dict(title="Día"), yaxis=dict(title="Llamadas", side="left"), yaxis2=dict(title="TMO (Min)", side="right", overlaying="y", showgrid=False), margin=dict(l=20, r=20, t=30, b=20))
            st.plotly_chart(fig_ev, use_container_width=True)