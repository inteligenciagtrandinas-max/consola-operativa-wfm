import streamlit as st
import pandas as pd
import duckdb
import glob
import os
import io
import math
from datetime import datetime, time, timedelta
import re

# ==============================================================================
# FUNCIONES DE NORMALIZACIÓN Y LIMPIEZA
# ==============================================================================
def normalizar_rut(val):
    if pd.isna(val) or val is None:
        return ""
    s = str(val).strip().upper().replace(".", "").replace(" ", "")
    if s.endswith(".0"):
        s = s[:-2]
    if not s or s in ['NONE', 'NAN', 'NAT', 'NULL', 'RUT', 'ACTIVOS', 'INACTIVOS', 'TOTAL', '--:--']:
        return ""
    if "-" in s:
        p = s.split("-")
        if len(p) >= 2:
            return f"{p[0]}-{p[1]}"
    if len(s) >= 2 and s[:-1].isdigit():
        return f"{s[:-1]}-{s[-1]}"
    return s

def detectar_col(columnas, palabras_clave, valor_defecto=None):
    for p in palabras_clave:
        for c in columnas:
            if p in str(c).lower().strip():
                return c
    return valor_defecto

def parsear_fecha_flexible(val):
    if pd.isna(val):
        return ""
    if isinstance(val, (datetime, pd.Timestamp)):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return s[:10]

def limpiar_hora(v):
    if pd.isna(v) or v is None:
        return "--:--"
    if isinstance(v, (datetime, time)):
        if v.hour == 0 and v.minute == 0 and v.second == 0:
            return "--:--"
        return v.strftime("%H:%M")
    s = str(v).strip().upper()
    if s in ["LIBRE", "VACACIONES", "LICENCIA", "NAN", "NONE", "", "00:00:00", "00:00", "--:--"]:
        return "--:--"
    if len(s) > 8 and " " in s:
        s = s.split(" ")[1]
    match = re.search(r'(\d{1,2}):(\d{2})', s)
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        if h == 0 and m == 0:
            return "--:--"
        return f"{h:02d}:{m:02d}"
    return "--:--"

patron_exc = re.compile(r'\b(LM|LICENCIA|VACACION(ES)?|PERMISO|FALTA|INASISTENCIA|MUTUAL|ACHS)\b')
patron_libre = re.compile(r'\b(LIBRE)\b')

# ==============================================================================
# EXTRACTOR DE PRONÓSTICO Y FÓRMULA MATEMÁTICA CALIBRADA (SIN SOBREINFLAR)
# ==============================================================================
@st.cache_data(show_spinner=False, max_entries=4)
def extraer_fc_para_predictivo(_hojas_dict, version_datos=1):
    fc_llam_map = {}
    fc_dot_map = {}
    if not _hojas_dict or not isinstance(_hojas_dict, dict):
        return fc_llam_map, fc_dot_map

    if "Cuadro de Mando" in _hojas_dict:
        df_cm = _hojas_dict["Cuadro de Mando"]
        header_idx = None
        for idx, row in df_cm.head(30).iterrows():
            row_upper = [str(x).upper().strip() for x in row.values]
            if any("INTERVALO" in x for x in row_upper) and any("10MIN" in x or "10 MIN" in x for x in row_upper):
                header_idx = idx
        if header_idx is not None:
            cols = []
            seen = {}
            for c in df_cm.iloc[header_idx].values:
                c_str = str(c).strip().upper()
                if c_str in seen:
                    seen[c_str] += 1
                    cols.append(f"{c_str}_{seen[c_str]}")
                else:
                    seen[c_str] = 0
                    cols.append(c_str)
            df_data = df_cm.iloc[header_idx + 1:].copy()
            df_data.columns = cols
            prev_fc_acum = 0
            for _, r in df_data.iterrows():
                int_val = str(r.get("INTERVALO", ""))
                if "-" in int_val or ":" in int_val:
                    try:
                        h_ini = int_val.split("-")[0].strip()
                        if ":" in h_ini:
                            h_str = f"{int(h_ini.split(':')[0]):02d}:{int(h_ini.split(':')[1]):02d}"
                            fc_col = next((c for c in df_data.columns if "LLAM. FC" in c), None)
                            if fc_col:
                                fc_val = pd.to_numeric(r[fc_col], errors="coerce")
                                if pd.notna(fc_val):
                                    fc_llam_map[h_str] = max(0, int(fc_val) - prev_fc_acum)
                                    prev_fc_acum = int(fc_val)
                            dot_col = next((c for c in df_data.columns if "DOTACION FC" in c), None)
                            if dot_col:
                                dot_val = pd.to_numeric(r[dot_col], errors="coerce")
                                if pd.notna(dot_val):
                                    fc_dot_map[h_str] = int(dot_val)
                    except Exception:
                        pass
    return fc_llam_map, fc_dot_map

def calcular_dotacion_ideal_realista(llamadas_30m: int, dot_fc_excel: int, plan_malla: int):
    if llamadas_30m > 0:
        erlangs = (float(llamadas_30m) * 330.0) / 1800.0
        agentes_en_linea = max(1, int(round(erlangs / 0.82)))
        dotacion_ideal = max(agentes_en_linea, int(round(agentes_en_linea / 0.88)))
        return dotacion_ideal, agentes_en_linea, int(llamadas_30m)

    if dot_fc_excel > 0:
        ag_lin = max(1, int(round(dot_fc_excel * 0.88)))
        llam_est = int(round((ag_lin * 0.82 * 1800.0) / 330.0))
        return int(dot_fc_excel), ag_lin, llam_est

    if plan_malla > 0:
        ag_lin = max(1, int(round(plan_malla * 0.88)))
        llam_est = int(round((ag_lin * 0.82 * 1800.0) / 330.0))
        return int(plan_malla), ag_lin, llam_est

    return 0, 0, 0

# ==============================================================================
# EXPORTADOR EXCEL EJECUTIVO FONDO BLANCO CON SEMÁFOROS
# ==============================================================================
@st.cache_data(show_spinner=False, max_entries=6)
def generar_excel_asistencia_visual(_df_tabla, nombre_hoja, titulo_reporte, firma_cache):
    df_tabla = _df_tabla.copy()
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_tabla.to_excel(writer, sheet_name=nombre_hoja, index=False, startrow=2)
        ws = writer.sheets[nombre_hoja]
        
        from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        max_col = len(df_tabla.columns)
        max_row = ws.max_row

        title_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
        header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        zebra_even = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
        zebra_odd = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

        fill_rojo_soft = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
        fill_amarillo_soft = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
        fill_verde_soft = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")

        title_font = Font(color="1E3A8A", bold=True, name="Segoe UI", size=13)
        header_font = Font(color="FFFFFF", bold=True, name="Segoe UI", size=10)
        base_font = Font(color="0F172A", bold=False, name="Segoe UI", size=10)
        font_verde = Font(color="15803D", bold=True, name="Segoe UI", size=10)
        font_amarillo = Font(color="B45309", bold=True, name="Segoe UI", size=10)
        font_rojo = Font(color="B91C1C", bold=True, name="Segoe UI", size=10)
        font_azul = Font(color="0369A1", bold=True, name="Segoe UI", size=10)
        font_morado = Font(color="7E22CE", bold=True, name="Segoe UI", size=10)

        thin_border = Border(
            left=Side(style='thin', color='CBD5E1'),
            right=Side(style='thin', color='CBD5E1'),
            top=Side(style='thin', color='CBD5E1'),
            bottom=Side(style='thin', color='CBD5E1')
        )

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

        ws.row_dimensions[3].height = 28
        col_names = list(df_tabla.columns)
        for col_idx in range(1, max_col + 1):
            cell = ws.cell(row=3, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin_border

        last_col_letter = get_column_letter(max_col)
        ws.auto_filter.ref = f"A3:{last_col_letter}{max_row}"
        ws.freeze_panes = "A4"

        for row_idx in range(4, max_row + 1):
            ws.row_dimensions[row_idx].height = 22
            bg_row = zebra_even if (row_idx % 2 == 0) else zebra_odd

            for col_idx in range(1, max_col + 1):
                col_name = col_names[col_idx - 1]
                cell = ws.cell(row=row_idx, column=col_idx)
                val_str = str(cell.value if cell.value is not None else "").strip()

                cell.fill = bg_row
                cell.font = base_font
                cell.border = thin_border
                cell.alignment = Alignment(
                    horizontal="left" if any(k in col_name for k in ["Acción", "Diagnóstico", "Estado", "Detalle"]) else "center",
                    vertical="center"
                )

                if col_name in ["Planificado", "Bloque FC (Plan)", "Malla Programada (Plan)"]:
                    cell.font = font_azul
                elif "Ideal Matemática" in col_name:
                    cell.font = font_morado
                elif col_name in ["Presentes Reales", "Presentes_Totales", "Dotación Proyectada en Vivo"]:
                    cell.fill = fill_verde_soft
                    cell.font = font_verde
                elif col_name in ["Ausentes Reales", "Ausentes_Reales", "Brecha Operativa", "Diferencia vs Bloque FC", "Diferencia vs Ideal"]:
                    try:
                        v_num = float(val_str.replace("+", "").replace("%", "").strip())
                        if "Diferencia" in col_name:
                            if v_num <= -4:
                                cell.fill = fill_rojo_soft
                                cell.font = font_rojo
                            elif v_num < 0:
                                cell.fill = fill_amarillo_soft
                                cell.font = font_amarillo
                            else:
                                cell.fill = fill_verde_soft
                                cell.font = font_verde
                        else:
                            if v_num > 0:
                                cell.fill = fill_rojo_soft
                                cell.font = font_rojo
                            else:
                                cell.font = font_verde
                    except Exception:
                        pass
                elif "Cumplimiento" in col_name or "Cobertura" in col_name:
                    try:
                        pct = float(val_str.replace("%", "").strip())
                        if pct >= 90:
                            cell.fill = fill_verde_soft
                            cell.font = font_verde
                        elif pct >= 82:
                            cell.fill = fill_amarillo_soft
                            cell.font = font_amarillo
                        else:
                            cell.fill = fill_rojo_soft
                            cell.font = font_rojo
                    except Exception:
                        pass
                elif "Diagnóstico" in col_name or "Estado" in col_name:
                    if "CRÍTICO" in val_str or "Déficit" in val_str:
                        cell.fill = fill_rojo_soft
                        cell.font = font_rojo
                    elif "ALERTA" in val_str or "Leve" in val_str:
                        cell.fill = fill_amarillo_soft
                        cell.font = font_amarillo
                    elif "ÓPTIMA" in val_str or "Completo" in val_str:
                        cell.fill = fill_verde_soft
                        cell.font = font_verde

        for col_idx in range(1, max_col + 1):
            col_letter = get_column_letter(col_idx)
            col_header = str(ws.cell(row=3, column=col_idx).value or "")
            max_len = len(col_header)
            for r_idx in range(4, min(max_row + 1, 200)):
                v = ws.cell(row=r_idx, column=col_idx).value
                if v is not None:
                    max_len = max(max_len, len(str(v)))
            ws.column_dimensions[col_letter].width = max(max_len + 5, 15)

    return output.getvalue()

# ==============================================================================
# RESCATE INTELIGENTE DE LOGIN/LOGOUT (BD + CARPETA LOCAL)
# ==============================================================================
def recuperar_datos_login(con, fecha_activa_str):
    df_bp = pd.DataFrame()
    nota_origen = ""

    try:
        existe_reg = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'registro_compartimientos_wfm'").fetchone()[0] > 0
        if existe_reg:
            res_slot = con.execute("SELECT nombre_archivo FROM registro_compartimientos_wfm WHERE slot_id = 'login'").fetchone()
            if res_slot and res_slot[0] == "VACIADO_MANUAL":
                return pd.DataFrame(), ""
    except Exception:
        pass

    try:
        existe_tabla = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'datos_login_logout'").fetchone()[0] > 0
        if existe_tabla:
            df_bp = con.execute(f"SELECT * FROM datos_login_logout WHERE fecha_gestion = '{fecha_activa_str}'").df()
            if df_bp.empty:
                df_bp = con.execute("SELECT * FROM datos_login_logout").df()
                if not df_bp.empty and 'fecha_gestion' in df_bp.columns:
                    ult_fecha = df_bp['fecha_gestion'].dropna().iloc[-1]
                    df_bp = df_bp[df_bp['fecha_gestion'] == ult_fecha].copy()
                    nota_origen = f"ℹ️ Mostrando el último reporte de conexiones disponible en memoria (lote: {ult_fecha})."
    except Exception:
        pass

    if df_bp.empty:
        archivos_csv = sorted(glob.glob("*.csv") + glob.glob("*.txt"), key=os.path.getmtime, reverse=True)
        for ruta in archivos_csv:
            nom_low = os.path.basename(ruta).lower()
            if "login" in nom_low or "logout" in nom_low or "sesion" in nom_low:
                try:
                    try:
                        df_local = pd.read_csv(ruta, sep=',', low_memory=False)
                    except Exception:
                        df_local = pd.read_csv(ruta, sep=';', low_memory=False)
                    if not df_local.empty:
                        df_local['fecha_gestion'] = fecha_activa_str
                        con.execute("DROP TABLE IF EXISTS datos_login_logout")
                        con.register("t_log_auto", df_local)
                        con.execute("CREATE TABLE datos_login_logout AS SELECT * FROM t_log_auto")
                        con.unregister("t_log_auto")
                        df_bp = df_local
                        nota_origen = f"✅ Archivo local '{os.path.basename(ruta)}' auto-vinculado automáticamente."
                        break
                except Exception:
                    pass

    return df_bp, nota_origen

# ==============================================================================
# MOTOR WFM COMPROBADO: PARRILLA ACTIVA VS CAMBIO DE PLATAFORMA / APOYO (+ DOMICILIO)
# ==============================================================================
@st.cache_data(show_spinner=False, max_entries=4)
def procesar_cruce_asistencia_cacheado(fecha_activa_str, version_datos, filas_bp, ventana_min_corte, _hojas_bbdd, _df_bp):
    hojas_bbdd = _hojas_bbdd
    df_bp = _df_bp.copy() if _df_bp is not None else pd.DataFrame()

    dict_nombres = {}
    dict_servicio_base = {}
    dict_estado_turnos = {}
    dict_estado_bbdd = {}
    dict_comuna = {}
    dict_direccion = {}

    hojas_maestras = [
        n for n in hojas_bbdd.keys()
        if str(n).upper().strip() in ["BBDD", "BDD", "CLIENTE FINAL", "MAESTRO", "BASE DATOS"]
    ]
    if not hojas_maestras:
        hojas_maestras = [
            n for n in hojas_bbdd.keys()
            if any(kw in str(n).upper() for kw in ["CLIENTE FINAL", "BBDD", "BDD", "MAESTRO"])
        ]

    hojas_maestras.sort(key=lambda x: 0 if str(x).upper().strip() == "BBDD" else 1)

    for h_nom in hojas_maestras:
        df_bdd = hojas_bbdd[h_nom].copy()
        if df_bdd.empty:
            continue
        c_rut = detectar_col(df_bdd.columns, ["rut"], df_bdd.columns[0])
        c_nom = detectar_col(df_bdd.columns, ["nombre eac", "nombres", "nombre", "ejecutivo"], None)
        c_ape_p = detectar_col(df_bdd.columns, ["apellidopaterno", "apellido paterno"], None)
        c_ape_m = detectar_col(df_bdd.columns, ["apellidomaterno", "apellido materno"], None)
        c_plat = detectar_col(df_bdd.columns, ["plataforma", "servicio", "canal"], None)
        c_est_t = detectar_col(df_bdd.columns, ["estado para turnos", "observaciones", "motivo inactividad"], None)
        c_est_b = detectar_col(df_bdd.columns, ["estado bbdd", "estado"], None)
        c_com = detectar_col(df_bdd.columns, ["distrito", "comuna"], None)
        c_dir = detectar_col(df_bdd.columns, ["dirección", "direccion", "domicilio"], None)

        df_bdd['RUT_NORM'] = df_bdd[c_rut].apply(normalizar_rut)
        df_val = df_bdd[df_bdd['RUT_NORM'].str.len() > 5].copy()

        if c_nom:
            if "nombre eac" in str(c_nom).lower() or not c_ape_p:
                serie_nom = df_val[c_nom].fillna("").astype(str).str.strip()
            else:
                n_s = df_val[c_nom].fillna("").astype(str).str.strip()
                a_p = df_val[c_ape_p].fillna("").astype(str).str.strip() if c_ape_p else ""
                a_m = df_val[c_ape_m].fillna("").astype(str).str.strip() if c_ape_m else ""
                serie_nom = (n_s + " " + a_p + " " + a_m).str.replace(r'\s+', ' ', regex=True).str.strip()
            for r_k, n_v in zip(df_val['RUT_NORM'], serie_nom):
                if r_k and n_v and n_v.upper() != "NAN" and r_k not in dict_nombres:
                    dict_nombres[r_k] = n_v.upper()

        if c_plat:
            for r_k, p_v in zip(df_val['RUT_NORM'], df_val[c_plat].fillna("").astype(str).str.strip()):
                if r_k and p_v and p_v.upper() != "NAN" and r_k not in dict_servicio_base:
                    dict_servicio_base[r_k] = p_v.upper()

        if c_est_t:
            for r_k, et_v in zip(df_val['RUT_NORM'], df_val[c_est_t].fillna("").astype(str).str.strip()):
                if r_k and et_v and et_v.upper() != "NAN" and r_k not in dict_estado_turnos:
                    dict_estado_turnos[r_k] = et_v.upper()

        if c_est_b:
            for r_k, eb_v in zip(df_val['RUT_NORM'], df_val[c_est_b].fillna("").astype(str).str.strip()):
                if r_k and eb_v and eb_v.upper() != "NAN" and r_k not in dict_estado_bbdd:
                    dict_estado_bbdd[r_k] = eb_v.upper()

        if c_com:
            for r_k, cm_v in zip(df_val['RUT_NORM'], df_val[c_com].fillna("").astype(str).str.strip()):
                if r_k and cm_v and cm_v.upper() not in ["NAN", "NONE", ""] and r_k not in dict_comuna:
                    dict_comuna[r_k] = cm_v.upper()

        if c_dir:
            for r_k, dr_v in zip(df_val['RUT_NORM'], df_val[c_dir].fillna("").astype(str).str.strip()):
                if r_k and dr_v and dr_v.upper() not in ["NAN", "NONE", ""] and r_k not in dict_direccion:
                    dict_direccion[r_k] = dr_v.upper()

    dict_estado_parrilla = {}
    df_turnos = pd.DataFrame()

    if "BASE CARGA" in hojas_bbdd:
        df_bc = hojas_bbdd["BASE CARGA"]
        c_fec_bc = detectar_col(df_bc.columns, ["fecha"], "FECHA")
        if c_fec_bc:
            df_bc_dia = df_bc[pd.to_datetime(df_bc[c_fec_bc], errors='coerce').dt.strftime('%Y-%m-%d') == fecha_activa_str].copy()
            if not df_bc_dia.empty:
                c_r = detectar_col(df_bc_dia.columns, ["rut"], df_bc_dia.columns[0])
                c_i = detectar_col(df_bc_dia.columns, ["hora_ini", "entrada"], None)
                c_t = detectar_col(df_bc_dia.columns, ["hora_ter", "salida"], None)
                c_est_bc = detectar_col(df_bc_dia.columns, ["estado"], None)

                df_bc_dia['RUT_NORM'] = df_bc_dia[c_r].apply(normalizar_rut)
                df_bc_dia = df_bc_dia[df_bc_dia['RUT_NORM'].str.len() > 5]

                if c_est_bc:
                    for r_k, e_v in zip(df_bc_dia['RUT_NORM'], df_bc_dia[c_est_bc].fillna("ACTIVO").astype(str).str.strip().str.upper()):
                        dict_estado_parrilla[r_k] = e_v

                if c_i and c_t:
                    df_turnos = pd.DataFrame({
                        'RUT': df_bc_dia['RUT_NORM'],
                        'HORA_INI': df_bc_dia[c_i],
                        'HORA_TER': df_bc_dia[c_t]
                    })

    for nombre_hoja, df_hoja in hojas_bbdd.items():
        if "PROGRAMACI" in str(nombre_hoja).upper() and not df_hoja.empty:
            c_ent, c_sal = None, None
            for i, val in enumerate(df_hoja.iloc[0]):
                if parsear_fecha_flexible(val) == fecha_activa_str:
                    c_ent = df_hoja.columns[i]
                    c_sal = df_hoja.columns[i+1] if i+1 < len(df_hoja.columns) else None
                    break

            col_rut_p = df_hoja.columns[0]
            col_nom_p = df_hoja.columns[1] if len(df_hoja.columns) > 1 else None
            col_est_p = df_hoja.columns[2] if len(df_hoja.columns) > 2 else None
            col_est_turnos_p = None
            for idx_c, val_h in enumerate(df_hoja.iloc[0]):
                if "ESTADO PARA TURNOS" in str(val_h).upper():
                    col_est_turnos_p = df_hoja.columns[idx_c]
                    break

            df_p_rows = df_hoja.iloc[1:].copy()
            df_p_rows['RUT_NORM'] = df_p_rows[col_rut_p].apply(normalizar_rut)
            df_p_rows = df_p_rows[df_p_rows['RUT_NORM'].str.len() > 5]

            for _, r_p in df_p_rows.iterrows():
                rk = r_p['RUT_NORM']
                if col_nom_p and rk not in dict_nombres and pd.notna(r_p.get(col_nom_p)):
                    dict_nombres[rk] = str(r_p.get(col_nom_p)).strip().upper()
                if col_est_p and rk not in dict_estado_parrilla and pd.notna(r_p.get(col_est_p)):
                    val_ep = str(r_p.get(col_est_p)).strip().upper()
                    if val_ep in ["ACTIVO", "INACTIVO"]:
                        dict_estado_parrilla[rk] = val_ep
                if col_est_turnos_p and pd.notna(r_p.get(col_est_turnos_p)):
                    val_et = str(r_p.get(col_est_turnos_p)).strip().upper()
                    if val_et and not val_et.isdigit():
                        dict_estado_turnos[rk] = val_et

            if df_turnos.empty and c_ent and c_sal:
                df_turnos = pd.DataFrame({
                    'RUT': df_p_rows['RUT_NORM'],
                    'HORA_INI': df_p_rows[c_ent],
                    'HORA_TER': df_p_rows[c_sal]
                })

    if not df_turnos.empty:
        df_turnos['HORA_INI'] = df_turnos['HORA_INI'].astype(str).str.strip().replace("nan", "")
        df_turnos = df_turnos[df_turnos['RUT'].str.len() > 5]
        df_turnos = df_turnos[df_turnos['HORA_INI'] != ""]
        df_turnos = df_turnos.drop_duplicates(subset=['RUT'], keep='first')

    ruts_en_malla = set(df_turnos['RUT'].unique()) if not df_turnos.empty else set()

    if not df_bp.empty:
        c_rut_bp = detectar_col(df_bp.columns, ["login_id", "cedula", "rut", "agent"], df_bp.columns[0])
        df_bp['RUT'] = df_bp[c_rut_bp].apply(normalizar_rut)

        c_nom_bp = detectar_col(df_bp.columns, ["agent", "agente", "nombre"], None)
        if c_nom_bp and c_nom_bp != c_rut_bp:
            for r_b, n_b in zip(df_bp['RUT'], df_bp[c_nom_bp].fillna("").astype(str).str.strip()):
                if r_b and n_b and r_b not in dict_nombres:
                    dict_nombres[r_b] = re.sub(r'\s+', ' ', n_b).upper()

        cols_tiempo = [c for c in df_bp.columns if c != c_rut_bp and c != 'fecha_gestion']
        c_login = detectar_col(cols_tiempo, ["login_time", "login_dt", "start_time", "login"], None)
        c_logout = detectar_col(cols_tiempo, ["logout_time", "logout_dt", "end_time", "logout"], None)

        df_bp['Login_DT'] = pd.to_datetime(df_bp[c_login], dayfirst=True, errors='coerce') if c_login else pd.NaT
        df_bp['Logout_DT'] = pd.to_datetime(df_bp[c_logout], dayfirst=True, errors='coerce') if c_logout else pd.NaT

        agrupado = df_bp.groupby('RUT').agg(
            Primer_Login=('Login_DT', 'min'),
            Ultimo_Login=('Login_DT', 'max'),
            Ultimo_Logout=('Logout_DT', 'max')
        ).reset_index()

        logouts_validos = agrupado['Ultimo_Logout'].dropna()
        if not logouts_validos.empty:
            max_report_time = logouts_validos.quantile(0.95)
        else:
            max_login = agrupado['Primer_Login'].max()
            max_report_time = max_login if pd.notna(max_login) else pd.NaT

        hora_evaluacion = max_report_time.time() if pd.notna(max_report_time) else datetime.now().time()
    else:
        max_report_time = pd.NaT
        hora_evaluacion = datetime.now().time()
        agrupado = pd.DataFrame(columns=['RUT', 'Primer_Login', 'Ultimo_Login', 'Ultimo_Logout'])

    if not df_turnos.empty:
        df_cruce = pd.merge(df_turnos, agrupado, on='RUT', how='outer')
    else:
        df_cruce = agrupado.copy()
        df_cruce['HORA_INI'] = "--:--"
        df_cruce['HORA_TER'] = "--:--"

    df_cruce = df_cruce.drop_duplicates(subset=['RUT'], keep='first')
    df_cruce = df_cruce[df_cruce['RUT'].astype(str).str.len() > 5].copy()

    def normalizar_nombre_servicio(s_raw):
        p = str(s_raw).upper().strip()
        if "WHATSAPP" in p:
            return "WHATSAPP"
        if "ENCUESTA" in p:
            return "ENCUESTAS"
        if "COMERCIAL" in p:
            return "COMERCIAL"
        if "WEB" in p:
            return "WEB"
        if any(k in p for k in ["PCE", "BACKOFFICE", "BACK"]):
            return "PCE / BACK"
        if "RRSS" in p:
            return "RRSS"
        if "MESA" in p:
            return "MESA DE AYUDA"
        if "FRONT" in p:
            return "FRONT"
        return p if p else "FRONT"

    def resolver_servicio_y_parrilla(row):
        rut = str(row['RUT'])
        en_malla = rut in ruts_en_malla
        est_parrilla = dict_estado_parrilla.get(rut, "ACTIVO" if en_malla else "NO_EN_PARRILLA")
        est_turnos = dict_estado_turnos.get(rut, "")
        est_bbdd = dict_estado_bbdd.get(rut, "")
        serv_base_raw = dict_servicio_base.get(rut, "FRONT" if en_malla else "")
        serv_base = normalizar_nombre_servicio(serv_base_raw) if (serv_base_raw or rut in dict_nombres) else "EXTRA / SIN BBDD"

        destino_apoyo = ""
        if "APOYO" in est_turnos:
            if "WHATSAPP" in est_turnos:
                destino_apoyo = "WHATSAPP"
            elif "PCE" in est_turnos or "BACK" in est_turnos:
                destino_apoyo = "PCE / BACK"
            elif "ENCUESTA" in est_turnos:
                destino_apoyo = "ENCUESTAS"
            elif "WEB" in est_turnos:
                destino_apoyo = "WEB"
            else:
                destino_apoyo = "OTRA PLATAFORMA"

        es_parrilla_activa = (en_malla and est_parrilla == "ACTIVO" and not destino_apoyo)
        return serv_base, destino_apoyo, est_parrilla, est_turnos, est_bbdd, es_parrilla_activa

    info_serv = df_cruce.apply(resolver_servicio_y_parrilla, axis=1)
    df_cruce['PLATAFORMA'] = [x[0] for x in info_serv]
    df_cruce['DESTINO_APOYO'] = [x[1] for x in info_serv]
    df_cruce['ESTADO_PARRILLA'] = [x[2] for x in info_serv]
    df_cruce['ESTADO_PARA_TURNOS'] = [x[3] for x in info_serv]
    df_cruce['ESTADO_BBDD'] = [x[4] for x in info_serv]
    df_cruce['EN_PARRILLA_ACTIVA'] = [x[5] for x in info_serv]

    df_cruce['NOMBRE'] = df_cruce['RUT'].apply(lambda x: dict_nombres.get(str(x), f"NN / NO REGISTRADO ({str(x)})"))
    df_cruce['COMUNA'] = df_cruce['RUT'].apply(lambda x: dict_comuna.get(str(x), "SANTIAGO"))
    df_cruce['DIRECCION'] = df_cruce['RUT'].apply(lambda x: dict_direccion.get(str(x), ""))
    df_cruce['HORA_INI_LIMPIA'] = df_cruce['HORA_INI'].apply(limpiar_hora)
    df_cruce['HORA_TER_LIMPIA'] = df_cruce['HORA_TER'].apply(limpiar_hora)

    ventana_segundos = int(ventana_min_corte) * 60

    def evaluar_estado_wfm(row):
        h_ini_s = str(row.get('HORA_INI', '--:--')).upper()
        est_t = str(row.get('ESTADO_PARA_TURNOS', '')).upper()
        est_b = str(row.get('ESTADO_BBDD', '')).upper()
        dest_apoyo = str(row.get('DESTINO_APOYO', '')).upper()
        en_parrilla_activa = bool(row.get('EN_PARRILLA_ACTIVA', False))

        p_log = row.get('Primer_Login')
        u_log = row.get('Ultimo_Login')
        u_out = row.get('Ultimo_Logout')

        try:
            h_ini = datetime.strptime(str(row.get('HORA_INI_LIMPIA', '--:--'))[:5], "%H:%M").time()
        except Exception:
            h_ini = None
        try:
            h_ter = datetime.strptime(str(row.get('HORA_TER_LIMPIA', '--:--'))[:5], "%H:%M").time()
        except Exception:
            h_ter = None

        is_connected = False
        if pd.notna(u_log):
            if pd.isna(u_out) or u_log >= u_out:
                is_connected = True
            elif pd.notna(max_report_time) and (max_report_time - u_out).total_seconds() <= ventana_segundos:
                is_connected = True

        if not en_parrilla_activa:
            if pd.notna(p_log):
                etiqueta_apoyo = f"🔄 CAMBIO PLAT. ({dest_apoyo})" if dest_apoyo else (
                    f"🔄 CONECTADO EN APOYO ({est_t})" if est_t and est_t != "ACTIVO" else "🔄 CAMBIO PLATAFORMA (Sin Parrilla)"
                )
                return etiqueta_apoyo, 8, "🔄 Conectado (Cambio Plataforma)"
            else:
                if patron_exc.search(est_t) or patron_exc.search(est_b) or patron_exc.search(h_ini_s):
                    return f"🟣 EXCEPCIÓN ({est_t or est_b or 'Lic/Vac'})", 6, "❌ No Presente (Excepción)"
                if dest_apoyo:
                    return f"⚪ ASIGNADO A {dest_apoyo} (Sin Login)", 7, "⚪ En Otra Plataforma"
                return "⚫ NO PROGRAMADO EN PARRILLA", 7, "⚪ Fuera de Parrilla"

        if pd.notna(p_log):
            if is_connected:
                return "🟢 CONECTADO (En Parrilla)", 1, "✅ Presente en Parrilla"
            else:
                if h_ter and hora_evaluacion > h_ter and (not h_ini or h_ini < h_ter):
                    return "⚪ TURNO FINALIZADO (Parrilla)", 5, "✅ Presente en Parrilla"
                return "🟡 EN PAUSA / DESCONECTADO (Parrilla)", 2, "✅ Presente en Parrilla"
        else:
            if patron_exc.search(est_t) or patron_exc.search(est_b) or patron_exc.search(h_ini_s):
                return "🟣 EXCEPCIÓN (Lic/Vac)", 6, "❌ Ausente (Excepción)"
            if patron_libre.search(h_ini_s):
                return "🟣 LIBRE POR MALLA", 6, "🟣 Día Libre"
            if h_ini:
                dt_ref = datetime.combine(datetime.today(), h_ini) + timedelta(minutes=15)
                dt_actual = datetime.combine(datetime.today(), hora_evaluacion)
                if hora_evaluacion < h_ini:
                    return "🔵 POR INGRESAR (Turno Futuro)", 4, "⏳ Por Ingresar"
                elif dt_actual <= dt_ref:
                    return "🟡 EN TOLERANCIA (15 Min)", 3, "⏳ En Tolerancia"
                else:
                    return "🔴 AUSENTE REAL (Parrilla)", 3, "❌ Ausente Real"
            return "🟣 LIBRE / SIN TURNO", 6, "🟣 Sin Turno"

    if df_cruce.empty:
        df_cruce['Estado_WFM'] = []
        df_cruce['Prioridad_Orden'] = []
        df_cruce['Presencia Sistema'] = []
    else:
        res_wfm = df_cruce.apply(evaluar_estado_wfm, axis=1)
        df_cruce['Estado_WFM'] = [x[0] for x in res_wfm]
        df_cruce['Prioridad_Orden'] = [x[1] for x in res_wfm]
        df_cruce['Presencia Sistema'] = [x[2] for x in res_wfm]

    df_cruce = df_cruce[df_cruce['Prioridad_Orden'] != 7].copy()

    return df_cruce

def _formatear_ficha_corta_ejecutivos(df_sub, max_items=6):
    if df_sub is None or df_sub.empty:
        return "Ninguno"
    items = []
    for _, r in df_sub.head(max_items).iterrows():
        partes_n = str(r.get("NOMBRE", "")).split()
        nom_corto = " ".join(partes_n[:2]) if len(partes_n) >= 2 else str(r.get("NOMBRE", ""))
        com = str(r.get("COMUNA", "")).strip()
        dir_s = str(r.get("DIRECCION", "")).strip()
        if dir_s and dir_s not in ["NAN", "NONE", ""]:
            ubic = f"{com}, {dir_s[:18]}"
        elif com and com not in ["NAN", "NONE", ""]:
            ubic = com
        else:
            ubic = "RM"
        items.append(f"• {nom_corto} ({ubic})")
    resto = len(df_sub) - max_items
    if resto > 0:
        items.append(f"<i>...y {resto} ejecutivo(s) más</i>")
    return "<br>".join(items)

# ==============================================================================
# RENDERIZADO PRINCIPAL DEL MÓDULO
# ==============================================================================
def renderizar_modulo_asistencia_comparativo(con, fecha_activa_str):
    es_admin = bool(
        st.session_state.get("es_admin_wfm", False)
        or st.session_state.get("permiso_wfm", "ADMIN") == "ADMIN"
        or str(st.session_state.get("usuario_actual", "GTR")).strip().upper() == "GTR"
    )

    st.markdown("""
    <style>
        .header-asistencia { 
            background: linear-gradient(135deg, rgba(30, 58, 138, 0.7) 0%, rgba(15, 23, 42, 0.8) 100%); 
            backdrop-filter: blur(12px); padding: 25px 30px; border-radius: 16px; 
            border-left: 6px solid #3B82F6; border-top: 1px solid rgba(255,255,255,0.1);
            border-bottom: 1px solid rgba(255,255,255,0.1); margin-bottom: 25px; 
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }
        .header-asistencia h3 { margin: 0; color: #FFFFFF; font-weight: 900; font-size: 2.2rem; }
        .header-asistencia p { margin: 5px 0 0 0; color: #94A3B8; font-size: 1.1rem; }
        
        .kpi-container {
            background: linear-gradient(145deg, #131D31 0%, #1E293B 100%);
            border-radius: 16px; border: 2px solid #334155;
            padding: 18px 14px; text-align: center; box-shadow: 0 8px 20px rgba(0,0,0,0.35);
            min-height: 118px; display: flex; flex-direction: column; justify-content: center;
        }
        .kpi-title { font-size: 0.84rem; color: #CBD5E1; font-weight: 800; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }
        .kpi-value { font-size: 2.25rem; font-weight: 900; color: #FFFFFF; line-height: 1.1; }
        .kpi-sub { font-size: 0.78rem; color: #94A3B8; margin-top: 4px; font-weight: 600; }

        .exec-banner {
            background: linear-gradient(135deg, rgba(30, 58, 138, 0.45) 0%, rgba(15, 23, 42, 0.9) 100%);
            border: 1px solid #3B82F6; border-radius: 14px; padding: 16px 20px; margin-bottom: 18px;
            color: #F8FAFC; font-size: 0.96rem; line-height: 1.55;
        }
        .hour-card-grid-5 {
            display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin: 16px 0 22px 0;
        }
        @media (max-width: 1250px) {
            .hour-card-grid-5 { grid-template-columns: repeat(3, 1fr); }
        }
        .hour-card {
            background: linear-gradient(145deg, #0F172A 0%, #1E293B 100%);
            border: 2px solid #334155; border-radius: 14px; padding: 16px 12px; text-align: center;
            box-shadow: 0 6px 16px rgba(0,0,0,0.35);
            display: flex; flex-direction: column; justify-content: center; min-height: 128px;
        }
        [data-testid="stDataFrame"] table thead tr th {
            background-color: #1E3A8A !important;
            color: #F8FAFC !important;
            font-weight: bold !important;
            text-transform: uppercase !important;
        }
    </style>
    <div class="header-asistencia">
        <h3>👥 Monitor de Asistencia Inteligente y WFM</h3>
        <p>Cruce exacto de Parrilla Activa vs Conexiones en Vivo, Comparativo por Bloques y Proyección Predictiva Matemática.</p>
    </div>
    """, unsafe_allow_html=True)

    con.execute("CREATE TABLE IF NOT EXISTS control_desconexiones_memoria (fecha VARCHAR, rut VARCHAR, motivo_manual VARCHAR, PRIMARY KEY (fecha, rut))")
    con.execute("""
        CREATE TABLE IF NOT EXISTS calibracion_dotacion_vivo (
            fecha VARCHAR,
            servicio VARCHAR,
            hora_corte VARCHAR,
            dotacion_real_bp INTEGER,
            ausencias_reales_man INTEGER,
            PRIMARY KEY (fecha, servicio)
        );
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS ausencias_manuales_tramo_wfm (
            id_reg VARCHAR PRIMARY KEY,
            fecha VARCHAR,
            servicio VARCHAR,
            tipo VARCHAR,
            rut VARCHAR,
            nombre VARCHAR,
            hora_ini VARCHAR,
            hora_ter VARCHAR,
            cantidad INTEGER,
            motivo VARCHAR
        );
    """)
    try:
        con.execute("ALTER TABLE calibracion_dotacion_vivo ADD COLUMN ausencias_reales_man INTEGER;")
    except Exception:
        pass

    hojas_bbdd = st.session_state.get("excel_colaciones_hojas", {})
    hojas_intervalos = st.session_state.get("excel_intervalos_hojas", hojas_bbdd)
    if "Cuadro de Mando" not in hojas_intervalos and "Cuadro de Mando" in hojas_bbdd:
        hojas_intervalos = hojas_bbdd

    df_bp, nota_origen = recuperar_datos_login(con, fecha_activa_str)

    if nota_origen:
        st.caption(nota_origen)

    if df_bp.empty and not hojas_bbdd:
        st.warning(f"⚠️ Faltan datos de Malla y de Conexión (Login/Logout) para el {fecha_activa_str}. Súbelos en la Ingesta de Datos.")
        return
    elif df_bp.empty:
        st.info(f"ℹ️ Visualizando Malla Planificada para el {fecha_activa_str} (Sin archivo CSV de Login/Logout cargado aún).")

    c_top_f1, c_top_f2 = st.columns([2.8, 1.2])
    with c_top_f2:
        ventana_min_corte = st.number_input(
            "⏱️ Ventana Corte Activo BP (min):",
            min_value=5, max_value=180, value=15, step=1,
            help="Bright Pattern actualiza sesiones activas cada 15 min (ej. 10:45 a 10:59)."
        )

    version_datos = st.session_state.get("version_datos", 1)
    df_cruce_full = procesar_cruce_asistencia_cacheado(fecha_activa_str, version_datos, len(df_bp), ventana_min_corte, hojas_bbdd, df_bp)

    if df_cruce_full.empty:
        st.warning(f"⚠️ No se encontraron turnos programados ni conexiones para el {fecha_activa_str}.")
        return

    motivos_db = con.execute(f"SELECT rut, motivo_manual FROM control_desconexiones_memoria WHERE fecha = '{fecha_activa_str}'").df()
    dict_manual = dict(zip(motivos_db['rut'], motivos_db['motivo_manual'])) if not motivos_db.empty else {}
    df_cruce_full = df_cruce_full.copy()
    df_cruce_full['Motivo_Manual'] = df_cruce_full['RUT'].map(dict_manual).fillna("")

    servs_base = set(df_cruce_full['PLATAFORMA'].dropna().unique())
    servs_apoyo = set([x for x in df_cruce_full['DESTINO_APOYO'].dropna().unique() if x])
    servicios_disp = ["TODOS"] + sorted(list(servs_base.union(servs_apoyo)))
    default_area = "FRONT" if "FRONT" in servicios_disp else "TODOS"

    with c_top_f1:
        sel_servicio = st.selectbox(
            "🏢 Filtrar Asistencia por Servicio / Segmento:",
            servicios_disp,
            index=servicios_disp.index(default_area) if default_area in servicios_disp else 0
        )

    if sel_servicio != "TODOS":
        df_cruce = df_cruce_full[
            (df_cruce_full['PLATAFORMA'] == sel_servicio) |
            (df_cruce_full['DESTINO_APOYO'] == sel_servicio)
        ].copy()
    else:
        df_cruce = df_cruce_full.copy()

    cal_guardada = con.execute(
        "SELECT hora_corte, dotacion_real_bp, ausencias_reales_man FROM calibracion_dotacion_vivo WHERE fecha = ? AND servicio = ?",
        [fecha_activa_str, sel_servicio]
    ).fetchone()

    df_bajas_man = con.execute(
        "SELECT * FROM ausencias_manuales_tramo_wfm WHERE fecha = ? AND servicio = ?",
        [fecha_activa_str, sel_servicio]
    ).df()
    tot_bajas_man_cupos = int(df_bajas_man["cantidad"].sum()) if not df_bajas_man.empty else 0

    st.markdown("<br>", unsafe_allow_html=True)
    t_asist, t_tramos, t_comp, t_pred = st.tabs([
        "👥 1. Asistencia y Presencia",
        "⏰ 2. Agentes por Tramo Horario",
        "📊 3. Cuadro Comparativo",
        "🔮 4. Cuadro Predictivo"
    ])

    # ==========================================================================
    # PESTAÑA 1: ASISTENCIA Y PRESENCIA
    # ==========================================================================
    with t_asist:
        c_kpi1, c_kpi2, c_kpi3, c_kpi4, c_kpi5 = st.columns(5)

        tot_con_linea_csv = len(df_cruce[df_cruce['Prioridad_Orden'] == 1])
        tot_pausa_fin = len(df_cruce[df_cruce['Prioridad_Orden'].isin([2, 5])])
        tot_presentes_parrilla = tot_con_linea_csv + tot_pausa_fin
        tot_aus_reales_csv = len(df_cruce[df_cruce['Prioridad_Orden'] == 3])
        tot_por_ingresar = len(df_cruce[df_cruce['Prioridad_Orden'] == 4])
        tot_exc = len(df_cruce[df_cruce['Prioridad_Orden'] == 6])
        tot_cambio_plat = len(df_cruce[df_cruce['Prioridad_Orden'] == 8])

        con_mostrar = int(cal_guardada[1]) if (cal_guardada and cal_guardada[1] is not None) else max(0, tot_con_linea_csv - tot_bajas_man_cupos)
        aus_mostrar = (int(cal_guardada[2]) if (cal_guardada and cal_guardada[2] is not None) else tot_aus_reales_csv) + tot_bajas_man_cupos

        c_kpi1.markdown(
            f"<div class='kpi-container' style='border-color:#059669;'><div class='kpi-title'>✅ Presentes (En Parrilla)</div>"
            f"<div class='kpi-value' style='color: #10B981;'>{tot_presentes_parrilla}</div>"
            f"<div class='kpi-sub'>Con Turno Activo y Login hoy</div></div>",
            unsafe_allow_html=True
        )
        c_kpi2.markdown(
            f"<div class='kpi-container' style='border-color:#0284C7;'><div class='kpi-title'>🟢 Conectados en Línea</div>"
            f"<div class='kpi-value' style='color: #38BDF8;'>{con_mostrar}</div>"
            f"<div class='kpi-sub'>CSV: {tot_con_linea_csv} | En Pausa/Fin: {tot_pausa_fin}</div></div>",
            unsafe_allow_html=True
        )
        c_kpi3.markdown(
            f"<div class='kpi-container' style='border-color:#D97706;'><div class='kpi-title'>🔄 Cambio Plat. / Apoyo</div>"
            f"<div class='kpi-value' style='color: #F59E0B;'>{tot_cambio_plat}</div>"
            f"<div class='kpi-sub'>Conectados fuera de Parrilla</div></div>",
            unsafe_allow_html=True
        )
        c_kpi4.markdown(
            f"<div class='kpi-container' style='border-color:#DC2626;'><div class='kpi-title'>🔴 Ausentes Reales</div>"
            f"<div class='kpi-value' style='color: #EF4444;'>{aus_mostrar}</div>"
            f"<div class='kpi-sub'>CSV: {tot_aus_reales_csv} (+{tot_bajas_man_cupos} manual) | Por entrar: {tot_por_ingresar}</div></div>",
            unsafe_allow_html=True
        )
        c_kpi5.markdown(
            f"<div class='kpi-container' style='border-color:#9333EA;'><div class='kpi-title'>🟣 Excepciones / Libres</div>"
            f"<div class='kpi-value' style='color: #C084FC;'>{tot_exc}</div>"
            f"<div class='kpi-sub'>Licencias, Vacaciones y Libres</div></div>",
            unsafe_allow_html=True
        )

        st.markdown("<br>", unsafe_allow_html=True)

        df_vista = df_cruce[[
            'RUT', 'NOMBRE', 'PLATAFORMA', 'COMUNA', 'HORA_INI_LIMPIA', 'HORA_TER_LIMPIA',
            'Presencia Sistema', 'Estado_WFM', 'Primer_Login', 'Ultimo_Logout',
            'Motivo_Manual', 'Prioridad_Orden'
        ]].copy()

        df_vista['Primer_Login'] = pd.to_datetime(df_vista['Primer_Login'], errors='coerce').dt.strftime("%H:%M:%S").fillna("--:--:--")
        df_vista['Ultimo_Logout'] = pd.to_datetime(df_vista['Ultimo_Logout'], errors='coerce').dt.strftime("%H:%M:%S").fillna("--:--:--")
        df_vista['Orden_Hora'] = df_vista['HORA_INI_LIMPIA'].apply(lambda x: "99:99" if x == "--:--" else x)
        df_vista.sort_values(by=['Prioridad_Orden', 'Orden_Hora'], ascending=[True, True], inplace=True)
        df_vista = df_vista.drop(columns=['Prioridad_Orden', 'Orden_Hora'])
        df_vista = df_vista.fillna("").astype(str).replace("nan", "")

        df_editado = st.data_editor(
            df_vista,
            column_config={
                "RUT": st.column_config.TextColumn("RUT", disabled=True),
                "NOMBRE": st.column_config.TextColumn("Nombre Ejecutivo", disabled=True),
                "PLATAFORMA": st.column_config.TextColumn("Servicio Base", disabled=True),
                "COMUNA": st.column_config.TextColumn("Comuna RM", disabled=True),
                "HORA_INI_LIMPIA": st.column_config.TextColumn("Entrada Turno", disabled=True),
                "HORA_TER_LIMPIA": st.column_config.TextColumn("Salida Turno", disabled=True),
                "Presencia Sistema": st.column_config.TextColumn("Condición Parrilla", disabled=True),
                "Estado_WFM": st.column_config.TextColumn("Estado Operativo WFM", disabled=True),
                "Primer_Login": st.column_config.TextColumn("1er Login (Llegada)", disabled=True),
                "Ultimo_Logout": st.column_config.TextColumn("Último Logout", disabled=True),
                "Motivo_Manual": st.column_config.SelectboxColumn(
                    "Justificar / Motivo",
                    options=["", "Cambio de Plataforma", "Apoyo WhatsApp/PCE", "Problema Técnico", "Permiso Excepcional", "Atraso Justificado", "Caída Internet", "Gestión GTR"],
                    disabled=not es_admin
                ),
            },
            hide_index=True,
            width="stretch",
            height=600,
            key="edicion_motivos_asistencia"
        )

        if es_admin:
            if st.button("💾 Guardar Justificaciones", width="stretch"):
                cambios = 0
                for _, row in df_editado.iterrows():
                    r_rut = row['RUT']
                    r_mot = str(row['Motivo_Manual']).strip()
                    if r_mot:
                        con.execute(f"INSERT OR REPLACE INTO control_desconexiones_memoria VALUES ('{fecha_activa_str}', '{r_rut}', '{r_mot}')")
                        cambios += 1
                    else:
                        con.execute(f"DELETE FROM control_desconexiones_memoria WHERE fecha = '{fecha_activa_str}' AND rut = '{r_rut}'")
                st.success(f"✅ Se guardaron {cambios} registros correctamente.")
                st.rerun()

    # ==========================================================================
    # PESTAÑA 2: AGENTES POR TRAMO HORARIO
    # ==========================================================================
    with t_tramos:
        st.markdown("#### ⏰ Control de Ingresos por Tramo Horario (Parrilla Activa)")
        try:
            df_tramos = df_cruce[
                (df_cruce['EN_PARRILLA_ACTIVA'] == True) &
                (df_cruce['Prioridad_Orden'] != 6) &
                (df_cruce['HORA_INI_LIMPIA'] != '--:--')
            ].copy()
            if not df_tramos.empty:
                tramos_unicos = sorted(df_tramos['HORA_INI_LIMPIA'].unique())
                tramo_seleccionado = st.selectbox("Seleccione Tramo Horario de Entrada:", tramos_unicos)
                df_filtrado_tramo = df_tramos[df_tramos['HORA_INI_LIMPIA'] == tramo_seleccionado].copy()
                vista_tramo = df_filtrado_tramo[['RUT', 'NOMBRE', 'PLATAFORMA', 'COMUNA', 'DIRECCION', 'HORA_INI_LIMPIA', 'Presencia Sistema', 'Estado_WFM', 'Primer_Login', 'Motivo_Manual']].copy()
                vista_tramo['Primer_Login'] = pd.to_datetime(vista_tramo['Primer_Login'], errors='coerce').dt.strftime("%H:%M:%S").fillna("No Registrado ❌")
                st.dataframe(vista_tramo, width="stretch", hide_index=True)
            else:
                st.info("No hay tramos horarios disponibles en la parrilla activa para este filtro.")
        except Exception as e:
            st.error(f"Error: {e}")

    # ==========================================================================
    # PESTAÑA 3: CUADRO COMPARATIVO (MODO BLANCO/NEGRO + TOOLTIP EJECUTIVOS)
    # ==========================================================================
    with t_comp:
        c_tit_comp, c_tema_comp, c_btn_comp = st.columns([1.8, 1.0, 1.0])
        c_tit_comp.markdown("#### 📊 Cuadro Comparativo de Ingresos por Bloque Horario")
        estilo_graf_comp = c_tema_comp.radio(
            "🎨 Fondo del Gráfico:",
            ["⚫ Negro", "⚪ Blanco"],
            index=0,
            horizontal=True,
            key="tema_graf_comp"
        )

        try:
            df_validos = df_cruce[
                (df_cruce['EN_PARRILLA_ACTIVA'] == True) &
                (~df_cruce['Prioridad_Orden'].isin([6, 7, 8])) &
                (df_cruce['HORA_INI_LIMPIA'] != '--:--')
            ].copy()

            if not df_validos.empty:
                ruts_baja_man = set(df_bajas_man[df_bajas_man["tipo"] == "EJECUTIVO"]["rut"].dropna().tolist()) if not df_bajas_man.empty else set()
                tramos_baja_man = {}
                if not df_bajas_man.empty:
                    for _, rb in df_bajas_man[df_bajas_man["tipo"] == "TRAMO"].iterrows():
                        h_i_b = str(rb["hora_ini"])
                        tramos_baja_man[h_i_b] = tramos_baja_man.get(h_i_b, 0) + int(rb["cantidad"])

                def estado_efectivo_entrada(row):
                    if str(row["RUT"]) in ruts_baja_man:
                        return 3
                    return int(row["Prioridad_Orden"])

                df_validos["Orden_Efectivo"] = df_validos.apply(estado_efectivo_entrada, axis=1)

                hover_pres_map = {}
                hover_aus_map = {}
                for h_b, grp_b in df_validos.groupby('HORA_INI_LIMPIA'):
                    df_p_b = grp_b[grp_b['Orden_Efectivo'].isin([1, 2, 5])]
                    df_a_b = grp_b[grp_b['Orden_Efectivo'] == 3]
                    hover_pres_map[h_b] = _formatear_ficha_corta_ejecutivos(df_p_b, max_items=6)
                    hover_aus_map[h_b] = _formatear_ficha_corta_ejecutivos(df_a_b, max_items=6)

                comp_df_base = df_validos.groupby('HORA_INI_LIMPIA').agg(
                    Planificado=('RUT', 'count'),
                    Presentes_Totales=('Orden_Efectivo', lambda x: int(x.isin([1, 2, 5]).sum())),
                    Ausentes_Reales=('Orden_Efectivo', lambda x: int((x == 3).sum())),
                    Por_Ingresar=('Orden_Efectivo', lambda x: int((x == 4).sum()))
                ).reset_index().rename(columns={'HORA_INI_LIMPIA': 'Bloque Entrada'})

                for idx_c, r_c in comp_df_base.iterrows():
                    b_ent = str(r_c["Bloque Entrada"])
                    extra_aus = tramos_baja_man.get(b_ent, 0)
                    if extra_aus > 0:
                        nuevos_aus = min(int(r_c["Planificado"]), int(r_c["Ausentes_Reales"]) + extra_aus)
                        nuevos_pres = max(0, int(r_c["Presentes_Totales"]) - extra_aus)
                        comp_df_base.at[idx_c, "Ausentes_Reales"] = nuevos_aus
                        comp_df_base.at[idx_c, "Presentes_Totales"] = nuevos_pres

                tot_plan_csv = int(comp_df_base['Planificado'].sum())
                tot_pres_csv = int(comp_df_base['Presentes_Totales'].sum())
                tot_aus_csv = int(comp_df_base['Ausentes_Reales'].sum())

                c_opt_eje, _ = st.columns([2.4, 1.6])
                mostrar_eje_continuo = c_opt_eje.checkbox(
                    "🕒 Mostrar todos los intervalos de 30 min en el eje (07:00 a 21:30, incluidos bloques sin inicio de turno)",
                    value=False
                )

                if mostrar_eje_continuo:
                    rango_completo = [t.strftime("%H:%M") for t in pd.date_range("07:00", "21:30", freq="30min").time]
                    df_eje = pd.DataFrame({'Bloque Entrada': rango_completo})
                    comp_df = pd.merge(df_eje, comp_df_base, on='Bloque Entrada', how='left').fillna(0)
                    for col_int in ['Planificado', 'Presentes_Totales', 'Ausentes_Reales', 'Por_Ingresar']:
                        comp_df[col_int] = comp_df[col_int].astype(int)
                else:
                    comp_df = comp_df_base.copy()

                comp_df['Hover_Presentes'] = comp_df['Bloque Entrada'].map(lambda h: hover_pres_map.get(h, "Ninguno"))
                comp_df['Hover_Ausentes'] = comp_df['Bloque Entrada'].map(lambda h: hover_aus_map.get(h, "Ninguno"))

                comp_df['Brecha Operativa'] = comp_df['Planificado'] - comp_df['Presentes_Totales']
                comp_df['% Cumplimiento'] = comp_df.apply(
                    lambda r: f"{(r['Presentes_Totales'] / r['Planificado'] * 100.0):.0f}%" if r['Planificado'] > 0 else "—",
                    axis=1
                )

                def diagnosticar_bloque_entrada(r):
                    if r['Planificado'] == 0:
                        return "⚪ Sin Ingresos Programados"
                    if r['Por_Ingresar'] > 0 and r['Presentes_Totales'] == 0:
                        return f"🔵 Turno Futuro ({r['Por_Ingresar']} por entrar)"
                    if r['Brecha Operativa'] <= 0:
                        return "🟢 Completo (100% En Línea)"
                    if r['Brecha Operativa'] == 1:
                        return "🟡 Leve (-1 Ejecutivo)"
                    return f"🔴 Déficit (-{int(r['Brecha Operativa'])} Ejecutivos)"

                comp_df['Estado del Bloque'] = comp_df.apply(diagnosticar_bloque_entrada, axis=1)

                tot_plan_ent = tot_plan_csv
                tot_pres_ent = tot_pres_csv
                tot_aus_ent = tot_aus_csv
                pct_adh_ent = (tot_pres_ent / tot_plan_ent * 100.0) if tot_plan_ent > 0 else 0.0

                k_c1, k_c2, k_c3, k_c4 = st.columns(4)
                k_c1.markdown(
                    f"<div class='kpi-container' style='border-color:#3B82F6;'><div class='kpi-title'>📋 Total Planificado (Bloque FC)</div>"
                    f"<div class='kpi-value' style='color:#38BDF8;'>{tot_plan_ent}</div>"
                    f"<div class='kpi-sub'>Ejecutivos citados hoy</div></div>",
                    unsafe_allow_html=True
                )
                k_c2.markdown(
                    f"<div class='kpi-container' style='border-color:#059669;'><div class='kpi-title'>✅ Total Presentes</div>"
                    f"<div class='kpi-value' style='color:#10B981;'>{tot_pres_ent}</div>"
                    f"<div class='kpi-sub'>Ingresaron a su turno</div></div>",
                    unsafe_allow_html=True
                )
                k_c3.markdown(
                    f"<div class='kpi-container' style='border-color:#DC2626;'><div class='kpi-title'>🚨 Ausentes Reales</div>"
                    f"<div class='kpi-value' style='color:#EF4444;'>{tot_aus_ent}</div>"
                    f"<div class='kpi-sub'>Incluye faltas por ejecutivo/tramo</div></div>",
                    unsafe_allow_html=True
                )
                col_adh = "#10B981" if pct_adh_ent >= 90 else "#F59E0B" if pct_adh_ent >= 80 else "#EF4444"
                k_c4.markdown(
                    f"<div class='kpi-container' style='border-color:{col_adh};'><div class='kpi-title'>🎯 Cumplimiento de Entrada</div>"
                    f"<div class='kpi-value' style='color:{col_adh};'>{pct_adh_ent:.1f}%</div>"
                    f"<div class='kpi-sub'>Presentes vs Bloque FC</div></div>",
                    unsafe_allow_html=True
                )

                st.markdown("<br>", unsafe_allow_html=True)

                df_comp_mostrar = comp_df[[
                    'Bloque Entrada', 'Planificado', 'Presentes_Totales',
                    'Ausentes_Reales', 'Brecha Operativa', '% Cumplimiento', 'Estado del Bloque'
                ]].rename(columns={
                    'Presentes_Totales': 'Presentes Reales',
                    'Ausentes_Reales': 'Ausentes Reales'
                })

                excel_comp_bytes = generar_excel_asistencia_visual(
                    df_comp_mostrar,
                    "Comparativo_Entrada",
                    f"Cuadro Comparativo de Ingresos por Bloque ({sel_servicio}) - {fecha_activa_str}",
                    f"comp_{fecha_activa_str}_{sel_servicio}_{tot_pres_ent}_{tot_aus_ent}_{mostrar_eje_continuo}"
                )
                with c_btn_comp:
                    st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)
                    st.download_button(
                        label="📥 Exportar Comparativo (Excel)",
                        data=excel_comp_bytes,
                        file_name=f"Comparativo_Bloques_Entrada_{sel_servicio}_{fecha_activa_str}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        width="stretch"
                    )

                try:
                    import plotly.graph_objects as go
                    es_blanco_c = "Blanco" in estilo_graf_comp
                    bg_plot_c = "#FFFFFF" if es_blanco_c else "#0A0F1D"
                    bg_paper_c = "#F8FAFC" if es_blanco_c else "#070B14"
                    txt_col_c = "#0F172A" if es_blanco_c else "#F8FAFC"
                    grid_col_c = "#CBD5E1" if es_blanco_c else "#334155"

                    fig_comp = go.Figure()

                    fig_comp.add_trace(go.Bar(
                        x=comp_df['Bloque Entrada'],
                        y=comp_df['Planificado'],
                        name="📋 Bloque FC (Planificado)",
                        marker_color="#2563EB",
                        text=comp_df['Planificado'].apply(lambda v: str(v) if v > 0 else ""),
                        textposition="outside",
                        textfont=dict(size=13, color="#1D4ED8" if es_blanco_c else "#93C5FD"),
                        hovertemplate="<b>🕒 Bloque %{x}</b><br>📋 Planificados: <b>%{y} ejecutivos</b><extra></extra>"
                    ))

                    fig_comp.add_trace(go.Bar(
                        x=comp_df['Bloque Entrada'],
                        y=comp_df['Presentes_Totales'],
                        name="✅ Presentes Reales",
                        marker_color="#10B981",
                        text=comp_df['Presentes_Totales'].apply(lambda v: str(v) if v > 0 else ""),
                        textposition="outside",
                        textfont=dict(size=13, color="#047857" if es_blanco_c else "#6EE7B7"),
                        customdata=comp_df['Hover_Presentes'],
                        hovertemplate="<b>🕒 Bloque %{x} — ✅ Presentes: %{y}</b><br><b>👤 Ejecutivos (Comuna/Domicilio):</b><br>%{customdata}<extra></extra>"
                    ))

                    fig_comp.add_trace(go.Bar(
                        x=comp_df['Bloque Entrada'],
                        y=comp_df['Ausentes_Reales'],
                        name="🔴 Ausentes (Faltan)",
                        marker_color="#EF4444",
                        text=comp_df['Ausentes_Reales'].apply(lambda v: str(v) if v > 0 else ""),
                        textposition="outside",
                        textfont=dict(size=13, color="#B91C1C" if es_blanco_c else "#FCA5A5"),
                        customdata=comp_df['Hover_Ausentes'],
                        hovertemplate="<b>🕒 Bloque %{x} — 🔴 Ausentes: %{y}</b><br><b>🚨 Quiénes faltaron (Comuna/Domicilio):</b><br>%{customdata}<extra></extra>"
                    ))

                    max_y_bar = max(10, int(comp_df['Planificado'].max()) + 4)
                    fig_comp.update_layout(
                        barmode='group',
                        template="plotly_white" if es_blanco_c else "plotly_dark",
                        height=470,
                        plot_bgcolor=bg_plot_c,
                        paper_bgcolor=bg_paper_c,
                        font=dict(color=txt_col_c, size=13),
                        legend=dict(orientation="h", yanchor="bottom", y=1.03, xanchor="right", x=1, font=dict(size=13, color=txt_col_c)),
                        xaxis=dict(title="Hora de Entrada del Turno", type="category", tickfont=dict(size=12, color=txt_col_c), gridcolor=grid_col_c, showgrid=True, linecolor=grid_col_c),
                        yaxis=dict(title="Cantidad de Ejecutivos que Inician Turno", range=[0, max_y_bar], tickfont=dict(color=txt_col_c), gridcolor=grid_col_c, showgrid=True, linecolor=grid_col_c),
                        margin=dict(l=25, r=25, t=45, b=30),
                        hoverlabel=dict(bgcolor="#0F172A", bordercolor="#38BDF8", font=dict(color="#F8FAFC", size=12))
                    )
                    st.plotly_chart(fig_comp, width="stretch")
                except Exception:
                    st.bar_chart(comp_df.set_index('Bloque Entrada')[['Planificado', 'Presentes_Totales', 'Ausentes_Reales']])

                st.markdown("##### 📋 Detalle por Bloque de Entrada (Coloreado por Nivel de Cumplimiento)")

                def style_brecha_roja(v):
                    try:
                        n = int(v)
                        if n >= 2:
                            return 'background-color: rgba(239, 68, 68, 0.28); color: #EF4444; font-weight: bold;'
                        elif n == 1:
                            return 'background-color: rgba(245, 158, 11, 0.25); color: #F59E0B; font-weight: bold;'
                        return 'color: #10B981; font-weight: bold;'
                    except Exception:
                        return ''

                def style_cumpl_pct(v):
                    s = str(v)
                    if s == "—":
                        return 'color: #64748B;'
                    try:
                        n = float(s.replace('%', ''))
                        if n >= 95:
                            return 'color: #10B981; font-weight: bold;'
                        elif n >= 85:
                            return 'color: #F59E0B; font-weight: bold;'
                        return 'background-color: rgba(239, 68, 68, 0.25); color: #EF4444; font-weight: bold;'
                    except Exception:
                        return ''

                def style_estado_bloque(v):
                    s = str(v)
                    if "Completo" in s:
                        return 'background-color: rgba(16, 185, 129, 0.2); color: #10B981; font-weight: bold;'
                    elif "Leve" in s:
                        return 'background-color: rgba(245, 158, 11, 0.22); color: #F59E0B; font-weight: bold;'
                    elif "Déficit" in s:
                        return 'background-color: rgba(239, 68, 68, 0.28); color: #EF4444; font-weight: bold;'
                    elif "Sin Ingresos" in s:
                        return 'color: #64748B;'
                    return 'color: #38BDF8; font-weight: bold;'

                max_plan = max(1, int(df_comp_mostrar['Planificado'].max()))
                styled_comp = (
                    df_comp_mostrar.style
                    .bar(subset=['Planificado'], color='#2563EB', vmin=0, vmax=max_plan)
                    .bar(subset=['Presentes Reales'], color='#059669', vmin=0, vmax=max_plan)
                    .map(style_brecha_roja, subset=['Ausentes Reales', 'Brecha Operativa'])
                    .map(style_cumpl_pct, subset=['% Cumplimiento'])
                    .map(style_estado_bloque, subset=['Estado del Bloque'])
                    .map(lambda _: 'color: #38BDF8; font-weight: bold;', subset=['Bloque Entrada'])
                )
                st.dataframe(styled_comp, width="stretch", hide_index=True, height=430)
            else:
                st.info("Datos insuficientes en la parrilla activa.")
        except Exception as e:
            st.error(f"Error en Cuadro Comparativo: {e}")

    # ==========================================================================
    # PESTAÑA 4: CUADRO PREDICTIVO EJECUTIVO (CON EJECUTIVO + DOTACIÓN REAL + AUSENCIAS REALES)
    # ==========================================================================
    with t_pred:
        c_tit_p, c_tema_p = st.columns([2.5, 1.1])
        c_tit_p.markdown("#### 🔮 Tablero Predictivo Hora a Hora & Diagnóstico Ejecutivo")
        estilo_graf_pred = c_tema_p.radio(
            "🎨 Fondo de la Curva:",
            ["⚫ Negro (Oscuro)", "⚪ Blanco (Claro)"],
            index=0,
            horizontal=True,
            key="tema_graf_pred"
        )

        st.markdown("""
        <div class="exec-banner">
            💡 <b>¿Cómo leer este tablero en 5 segundos?</b><br>
            • <b style="color:#38BDF8;">📋 Bloque FC (Línea Azul):</b> Es la dotación planificada por bloque horario según la programación.<br>
            • <b style="color:#C084FC;">🧮 Dotación Ideal Matemática (Línea Morada):</b> Calcula automáticamente cuántos ejecutivos exige el volumen de llamadas pronosticado del bloque.<br>
            • <b style="color:#10B981;">🟢 Capacidad Proyectada en Vivo (Línea Verde):</b> Pasa el mouse sobre cualquier punto para ver <b>quiénes son los ejecutivos ausentes o conectados y en qué comuna/dirección viven</b>.
        </div>
        """, unsafe_allow_html=True)

        try:
            df_pred = df_cruce[df_cruce['EN_PARRILLA_ACTIVA'] == True].copy()
            if not df_pred.empty:
                rng = pd.date_range("08:00", "23:30", freq="30min").time
                bloques_str_list = [t.strftime("%H:%M") for t in rng]

                fc_llam_map, fc_dot_map = extraer_fc_para_predictivo(hojas_intervalos, version_datos)

                def a_minutos(val):
                    try:
                        h, m = map(int, str(val)[:5].split(':'))
                        return h * 60 + m
                    except Exception:
                        return -1

                df_pred['ini_m'] = df_pred['HORA_INI_LIMPIA'].apply(a_minutos)
                df_pred['ter_m'] = df_pred['HORA_TER_LIMPIA'].apply(a_minutos)

                mask_validos = (df_pred['ini_m'] >= 0) & (df_pred['ter_m'] >= 0)
                df_val = df_pred[mask_validos].copy()
                df_val['es_trasnoche'] = df_val['ini_m'] > df_val['ter_m']
                mask_real_csv = ~df_val['Prioridad_Orden'].isin([3, 6, 7, 8])

                # Calcular base por bloque para inicializar los campos manuales
                base_plan_map = {}
                base_csv_map = {}
                base_aus_map = {}
                for t in rng:
                    h_lbl = t.strftime("%H:%M")
                    t_m = t.hour * 60 + t.minute
                    cond_normal = (~df_val['es_trasnoche']) & (df_val['ini_m'] <= t_m) & (t_m < df_val['ter_m'])
                    cond_trasnoche = (df_val['es_trasnoche']) & ((t_m >= df_val['ini_m']) | (t_m < df_val['ter_m']))
                    mask_activos = cond_normal | cond_trasnoche
                    p_t = int(mask_activos.sum())
                    c_t = int((mask_activos & mask_real_csv).sum())
                    base_plan_map[h_lbl] = p_t
                    base_csv_map[h_lbl] = c_t
                    base_aus_map[h_lbl] = max(0, p_t - c_t)

                ahora_h = datetime.now().hour
                ahora_m = 30 if datetime.now().minute >= 30 else 0
                bloque_ahora_default = f"{ahora_h:02d}:{ahora_m:02d}"
                if bloque_ahora_default not in bloques_str_list:
                    bloque_ahora_default = "20:00"

                hora_cal_def = cal_guardada[0] if (cal_guardada and cal_guardada[0] in bloques_str_list) else bloque_ahora_default

                # ==================================================================
                # PANEL VISIBLE GTR: EJECUTIVO AUSENTE + DOTACIÓN REAL MANUAL + AUSENCIAS REALES
                # ==================================================================
                if es_admin:
                    with st.expander("🛠️ Panel Rápido GTR: Elegir Ejecutivo Ausente, Dotación Real Manual y Ausencias Reales", expanded=True):
                        c_gtr1, c_gtr2 = st.columns([1.5, 1.5])

                        # Columna Izquierda: Selección directa de Ejecutivo(s) que faltaron
                        with c_gtr1:
                            df_cand_ejec = df_val[mask_real_csv].sort_values(by=['HORA_INI_LIMPIA', 'NOMBRE']).copy()
                            opciones_ejec = {}
                            for _, r_ej in df_cand_ejec.iterrows():
                                lbl_ej = f"{r_ej['NOMBRE']} ({r_ej['HORA_INI_LIMPIA']} a {r_ej['HORA_TER_LIMPIA']} • {r_ej['COMUNA']})"
                                opciones_ejec[lbl_ej] = (str(r_ej['RUT']), str(r_ej['NOMBRE']), str(r_ej['HORA_INI_LIMPIA']), str(r_ej['HORA_TER_LIMPIA']))

                            ruts_ya_marcados = set(df_bajas_man[df_bajas_man["tipo"] == "EJECUTIVO"]["rut"].dropna().tolist()) if not df_bajas_man.empty else set()
                            defaults_ejec = [k for k, v in opciones_ejec.items() if v[0] in ruts_ya_marcados]

                            sel_ejecutivos_baja = st.multiselect(
                                "👤 1. Elegir Ejecutivo(s) con Falta / Desconexión (Descuenta su turno):",
                                options=list(opciones_ejec.keys()),
                                default=defaults_ejec
                            )

                        # Columna Derecha: Hora de Corte + Dotación Real Manual + Ausencias Reales Manuales
                        with c_gtr2:
                            cm_h, cm_dot, cm_aus = st.columns([1.0, 1.1, 1.1])
                            hora_corte_sel = cm_h.selectbox(
                                "⏰ 2. Bloque Horario:",
                                bloques_str_list,
                                index=bloques_str_list.index(hora_cal_def)
                            )
                            plan_corte = base_plan_map.get(hora_corte_sel, 0)
                            csv_corte = max(0, base_csv_map.get(hora_corte_sel, 0) - len(sel_ejecutivos_baja))
                            aus_corte = max(0, plan_corte - csv_corte)

                            if cal_guardada and cal_guardada[0] == hora_corte_sel:
                                dot_init = int(cal_guardada[1]) if cal_guardada[1] is not None else csv_corte
                                aus_init = int(cal_guardada[2]) if cal_guardada[2] is not None else aus_corte
                            else:
                                dot_init = csv_corte
                                aus_init = aus_corte

                            in_dot_real_man = cm_dot.number_input(
                                "🟢 3. Dotación Real Manual:",
                                min_value=0, max_value=500, value=int(dot_init), step=1,
                                help="Ingresa la dotación real conectada ahora en BrightPattern."
                            )
                            in_aus_real_man = cm_aus.number_input(
                                "🔴 4. Ausencias Reales:",
                                min_value=0, max_value=500, value=int(aus_init), step=1,
                                help="Ingresa las ausencias reales confirmadas en este bloque."
                            )

                        cb_save, cb_reset = st.columns([2.2, 1.0])
                        if cb_save.button("💾 Aplicar Ejecutivo(s), Dotación Real y Ausencias Reales", width="stretch", key="btn_apply_all_gtr"):
                            con.execute(
                                "DELETE FROM ausencias_manuales_tramo_wfm WHERE fecha = ? AND servicio = ? AND tipo = 'EJECUTIVO'",
                                [fecha_activa_str, sel_servicio]
                            )
                            for item_k in sel_ejecutivos_baja:
                                rut_e, nom_e, hi_e, ht_e = opciones_ejec[item_k]
                                id_r = f"EJ_{fecha_activa_str}_{sel_servicio}_{rut_e}"
                                con.execute(
                                    "INSERT OR REPLACE INTO ausencias_manuales_tramo_wfm VALUES (?, ?, ?, 'EJECUTIVO', ?, ?, ?, ?, 1, 'Baja Manual GTR')",
                                    [id_r, fecha_activa_str, sel_servicio, rut_e, nom_e, hi_e, ht_e]
                                )
                            con.execute(
                                "INSERT OR REPLACE INTO calibracion_dotacion_vivo (fecha, servicio, hora_corte, dotacion_real_bp, ausencias_reales_man) VALUES (?, ?, ?, ?, ?)",
                                [fecha_activa_str, sel_servicio, hora_corte_sel, int(in_dot_real_man), int(in_aus_real_man)]
                            )
                            st.toast(f"✅ Actualizado en vivo para las {hora_corte_sel} hrs.", icon="🔮")
                            st.rerun()

                        if cb_reset.button("🔄 Restaurar Datos Originales CSV", width="stretch", key="btn_reset_all_gtr"):
                            con.execute("DELETE FROM ausencias_manuales_tramo_wfm WHERE fecha = ? AND servicio = ?", [fecha_activa_str, sel_servicio])
                            con.execute("DELETE FROM calibracion_dotacion_vivo WHERE fecha = ? AND servicio = ?", [fecha_activa_str, sel_servicio])
                            st.rerun()
                else:
                    hora_corte_sel = hora_cal_def

                # ==================================================================
                # MOTOR AUTOMÁTICO DE CÁLCULO HORA A HORA (+ TOOLTIP DE EJECUTIVOS)
                # ==================================================================
                ruts_baja_ejec = set(df_bajas_man[df_bajas_man["tipo"] == "EJECUTIVO"]["rut"].dropna().tolist()) if not df_bajas_man.empty else set()
                df_tramos_man = df_bajas_man[df_bajas_man["tipo"] == "TRAMO"].copy() if not df_bajas_man.empty else pd.DataFrame()

                prediccion_rows = []
                for idx_b, t in enumerate(rng):
                    h_lbl = t.strftime("%H:%M")
                    t_m = t.hour * 60 + t.minute

                    cond_normal = (~df_val['es_trasnoche']) & (df_val['ini_m'] <= t_m) & (t_m < df_val['ter_m'])
                    cond_trasnoche = (df_val['es_trasnoche']) & ((t_m >= df_val['ini_m']) | (t_m < df_val['ter_m']))
                    mask_activos = cond_normal | cond_trasnoche

                    df_bloque_act = df_val[mask_activos]
                    plan_b = int(len(df_bloque_act))

                    df_bloque_csv = df_bloque_act[~df_bloque_act['Prioridad_Orden'].isin([3, 6, 7, 8])]
                    df_ausentes_csv_b = df_bloque_act[df_bloque_act['Prioridad_Orden'] == 3]
                    csv_b = int(len(df_bloque_csv))
                    aus_csv_b = max(0, plan_b - csv_b)

                    df_bajas_ej_en_bloque = df_bloque_csv[df_bloque_csv['RUT'].astype(str).isin(ruts_baja_ejec)]
                    df_conectados_efectivos_b = df_bloque_csv[~df_bloque_csv['RUT'].astype(str).isin(ruts_baja_ejec)]

                    cant_baja_ej_b = int(len(df_bajas_ej_en_bloque))
                    nombres_baja_b = [str(n).split()[0] + " " + (str(n).split()[1] if len(str(n).split()) > 1 else "") for n in df_bajas_ej_en_bloque['NOMBRE'].tolist()]

                    cant_baja_tr_b = 0
                    if not df_tramos_man.empty:
                        for _, r_tr in df_tramos_man.iterrows():
                            ini_tr_m = a_minutos(r_tr["hora_ini"])
                            ter_tr_m = 24 * 60 if str(r_tr["hora_ter"]) == "23:59" else a_minutos(r_tr["hora_ter"])
                            if ini_tr_m <= t_m < ter_tr_m:
                                cant_baja_tr_b += int(r_tr["cantidad"])
                                nombres_baja_b.append(f"-{int(r_tr['cantidad'])} ({r_tr['hora_ini']}-{r_tr['hora_ter']})")

                    bajas_man_bloque = cant_baja_ej_b + cant_baja_tr_b
                    proy_vivo = max(0, csv_b - bajas_man_bloque)
                    aus_totales_bloque = max(0, plan_b - proy_vivo)

                    # Si hay calibración manual de Dotación Real o Ausencias Reales en el bloque
                    if cal_guardada and h_lbl == cal_guardada[0]:
                        dot_man_db = cal_guardada[1]
                        aus_man_db = cal_guardada[2]
                        if dot_man_db is not None and int(dot_man_db) != csv_b:
                            proy_vivo = int(dot_man_db)
                            aus_totales_bloque = int(aus_man_db) if (aus_man_db is not None and int(aus_man_db) != aus_csv_b) else max(0, plan_b - proy_vivo)
                        elif aus_man_db is not None and int(aus_man_db) != aus_csv_b:
                            aus_totales_bloque = int(aus_man_db)
                            proy_vivo = max(0, plan_b - aus_totales_bloque)

                    llam_fc_bloque = int(fc_llam_map.get(h_lbl, 0))
                    dot_fc_bloque = int(fc_dot_map.get(h_lbl, 0))
                    dot_math_total, ag_linea_req, llam_usadas = calcular_dotacion_ideal_realista(
                        llam_fc_bloque, dot_fc_bloque, plan_b
                    )

                    brecha_vs_plan = proy_vivo - plan_b
                    brecha_vs_math = proy_vivo - dot_math_total
                    cobertura_pct = (proy_vivo / plan_b * 100.0) if plan_b > 0 else 100.0

                    if plan_b == 0 and dot_math_total == 0:
                        diag = "⚪ Sin Turno Programado"
                        accion = "Sin operación planificada"
                    elif brecha_vs_plan >= -1 and brecha_vs_math >= 0:
                        diag = "🟢 CAPACIDAD ÓPTIMA"
                        accion = f"Demanda cubierta al 100% ({llam_usadas} llam. est.)"
                    elif brecha_vs_plan >= -3 and brecha_vs_math >= -2:
                        diag = f"🟡 ALERTA LEVE ({brecha_vs_plan:+d} vs FC)"
                        accion = "Tráfico cubierto — Cuidar tiempos de pausa y colación"
                    else:
                        faltantes_real = abs(min(brecha_vs_plan, brecha_vs_math))
                        diag = f"🔴 DÉFICIT CRÍTICO (-{faltantes_real} ag.)"
                        accion = f"Faltan {faltantes_real} ejecutivos en este bloque — Reprogramar pausas / Apoyo"

                    detalle_impacto = f"Ausentes CSV: {aus_csv_b}"
                    if bajas_man_bloque > 0:
                        detalle_impacto += f" | Bajas GTR: -{bajas_man_bloque} ({', '.join(nombres_baja_b[:2])})"
                    elif cal_guardada and h_lbl == cal_guardada[0] and aus_totales_bloque != aus_csv_b:
                        detalle_impacto = f"Ajuste Manual GTR: {aus_totales_bloque} ausentes"

                    df_todos_aus_b = pd.concat([df_ausentes_csv_b, df_bajas_ej_en_bloque]).drop_duplicates(subset=['RUT'])
                    hover_aus_txt = _formatear_ficha_corta_ejecutivos(df_todos_aus_b, max_items=5)
                    hover_con_txt = _formatear_ficha_corta_ejecutivos(df_conectados_efectivos_b, max_items=5)

                    prediccion_rows.append({
                        "Hora Bloque": h_lbl,
                        "Bloque FC (Plan)": plan_b,
                        "Dotación Ideal Matemática": dot_math_total,
                        "Agentes Línea Req": ag_linea_req,
                        "Llamadas Bloque Est": llam_usadas,
                        "Base CSV (Sin Ajuste)": csv_b,
                        "Dotación Proyectada en Vivo": proy_vivo,
                        "Ausencias Reales": aus_totales_bloque,
                        "Bajas Manuales Bloque": bajas_man_bloque,
                        "Detalle Impacto Tramo": detalle_impacto,
                        "Hover_Ausentes": hover_aus_txt,
                        "Hover_Conectados": hover_con_txt,
                        "Diferencia vs Bloque FC": brecha_vs_plan,
                        "Diferencia vs Ideal": brecha_vs_math,
                        "% Cobertura": f"{cobertura_pct:.0f}%",
                        "Cobertura_Num": cobertura_pct,
                        "Diagnóstico Gerencial": diag,
                        "Acción Recomendada WFM": accion
                    })

                df_res = pd.DataFrame(prediccion_rows)

                # ==================================================================
                # INSPECTOR EJECUTIVO HORA A HORA (VISTA PRINCIPAL PARA GERENCIA)
                # ==================================================================
                st.markdown("##### 🕒 Inspector Ejecutivo Hora a Hora (Desliza para consultar cualquier hora del día)")
                c_insp_sel, c_insp_exp = st.columns([1.8, 1.2])
                hora_inspeccion = c_insp_sel.select_slider(
                    "Selecciona el bloque horario que deseas revisar:",
                    options=bloques_str_list,
                    value=hora_corte_sel if hora_corte_sel in bloques_str_list else "20:00"
                )

                df_export_pred = df_res[[
                    "Hora Bloque", "Bloque FC (Plan)", "Dotación Ideal Matemática",
                    "Dotación Proyectada en Vivo", "Ausencias Reales", "Detalle Impacto Tramo",
                    "Diferencia vs Bloque FC", "% Cobertura", "Diagnóstico Gerencial", "Acción Recomendada WFM"
                ]].copy()

                excel_pred_bytes = generar_excel_asistencia_visual(
                    df_export_pred,
                    "Proyeccion_Hora_a_Hora",
                    f"Tablero Predictivo de Dotación Hora a Hora ({sel_servicio}) - {fecha_activa_str}",
                    f"pred_fc_cal2_{fecha_activa_str}_{sel_servicio}_{len(df_bajas_man)}_{tot_bajas_man_cupos}_{cal_guardada}"
                )
                with c_insp_exp:
                    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
                    st.download_button(
                        label="📥 Descargar Proyección Hora a Hora (Excel)",
                        data=excel_pred_bytes,
                        file_name=f"Proyeccion_Predictiva_{sel_servicio}_{fecha_activa_str}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        width="stretch"
                    )

                fila_h = df_res[df_res["Hora Bloque"] == hora_inspeccion].iloc[0]
                p_h = int(fila_h["Bloque FC (Plan)"])
                math_h = int(fila_h["Dotación Ideal Matemática"])
                ag_lin_h = int(fila_h["Agentes Línea Req"])
                llam_h = int(fila_h["Llamadas Bloque Est"])
                r_h = int(fila_h["Dotación Proyectada en Vivo"])
                aus_h = int(fila_h["Ausencias Reales"])
                det_h = fila_h["Detalle Impacto Tramo"]
                d_plan_h = int(fila_h["Diferencia vs Bloque FC"])
                d_math_h = int(fila_h["Diferencia vs Ideal"])
                cob_h = float(fila_h["Cobertura_Num"])
                diag_h = fila_h["Diagnóstico Gerencial"]
                acc_h = fila_h["Acción Recomendada WFM"]

                col_sem_h = "#10B981" if "ÓPTIMA" in diag_h else "#F59E0B" if "ALERTA" in diag_h else "#EF4444"
                res_math_txt = f"Superávit {d_math_h:+d} ag." if d_math_h >= 0 else f"Faltan {abs(d_math_h)} ag. vs Llamadas"

                st.markdown(f"""
                <div class="hour-card-grid-5">
                    <div class="hour-card" style="border-color:#3B82F6;">
                        <div class="kpi-title">🕒 BLOQUE CONSULTADO</div>
                        <div class="kpi-value" style="color:#38BDF8;">{hora_inspeccion} hrs</div>
                        <div class="kpi-sub">📋 Bloque FC: <b>{p_h} ejecutivos</b></div>
                    </div>
                    <div class="hour-card" style="border-color:#A855F7;">
                        <div class="kpi-title">🧮 DOTACIÓN IDEAL MATEMÁTICA</div>
                        <div class="kpi-value" style="color:#C084FC;">{math_h} <span style="font-size:1.15rem; color:#E9D5FF;">({ag_lin_h} línea)</span></div>
                        <div class="kpi-sub" style="color:#E9D5FF;"><b>{res_math_txt}</b> ({llam_h} llam.)</div>
                    </div>
                    <div class="hour-card" style="border-color:{col_sem_h};">
                        <div class="kpi-title">🟢 CONECTADOS PROYECTADOS</div>
                        <div class="kpi-value" style="color:{col_sem_h};">{r_h} <span style="font-size:1.25rem;">({cob_h:.0f}%)</span></div>
                        <div class="kpi-sub">Vs Bloque FC: <b>{d_plan_h:+d}</b> | Vs Ideal: <b>{d_math_h:+d} ag.</b></div>
                    </div>
                    <div class="hour-card" style="border-color:#DC2626;">
                        <div class="kpi-title">🔴 AUSENCIAS EN ESTE HORARIO</div>
                        <div class="kpi-value" style="color:#EF4444;">{aus_h}</div>
                        <div class="kpi-sub">{det_h}</div>
                    </div>
                    <div class="hour-card" style="border-color:{col_sem_h};">
                        <div class="kpi-title">🚦 DIAGNÓSTICO PARA GERENCIA</div>
                        <div style="font-size:1.15rem; font-weight:900; color:{col_sem_h}; margin:5px 0;">{diag_h}</div>
                        <div class="kpi-sub" style="color:#E2E8F0;">{acc_h}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # ==================================================================
                # GRÁFICO PREDICTIVO CON MODO BLANCO/NEGRO NÍTIDO Y TOOLTIP DE EJECUTIVOS
                # ==================================================================
                import plotly.graph_objects as go
                es_blanco_p = "Blanco" in estilo_graf_pred
                bg_plot_p = "#FFFFFF" if es_blanco_p else "#0A0F1D"
                bg_paper_p = "#F8FAFC" if es_blanco_p else "#070B14"
                txt_col_p = "#0F172A" if es_blanco_p else "#F8FAFC"
                grid_col_p = "#CBD5E1" if es_blanco_p else "#334155"

                fig2 = go.Figure()

                fig2.add_trace(go.Scatter(
                    x=df_res['Hora Bloque'],
                    y=df_res['Bloque FC (Plan)'],
                    name="📋 Bloque FC (Dotación Planificada)",
                    mode="lines+markers+text",
                    line=dict(color="#2563EB" if es_blanco_p else "#38BDF8", width=3, dash='dot'),
                    marker=dict(size=7, color="#2563EB" if es_blanco_p else "#38BDF8"),
                    text=[str(v) if i % 2 == 0 else "" for i, v in enumerate(df_res['Bloque FC (Plan)'])],
                    textposition="top center",
                    textfont=dict(size=11, color="#1D4ED8" if es_blanco_p else "#93C5FD"),
                    hovertemplate="<b>🕒 %{x} hrs</b><br>📋 Bloque FC: <b>%{y} ejecutivos</b><extra></extra>"
                ))

                fig2.add_trace(go.Scatter(
                    x=df_res['Hora Bloque'],
                    y=df_res['Dotación Ideal Matemática'],
                    name="🧮 Dotación Ideal Matemática (Según Llamadas)",
                    mode="lines+markers",
                    line=dict(color="#7E22CE" if es_blanco_p else "#C084FC", width=2.5, dash='dashdot'),
                    marker=dict(size=6, color="#7E22CE" if es_blanco_p else "#C084FC", symbol="diamond"),
                    hovertemplate="<b>🕒 %{x} hrs</b><br>🧮 Ideal Matemática: <b>%{y} ejecutivos</b><extra></extra>"
                ))

                fig2.add_trace(go.Scatter(
                    x=df_res['Hora Bloque'],
                    y=df_res['Dotación Proyectada en Vivo'],
                    name="🟢 Capacidad Proyectada en Vivo (Real)",
                    mode="lines+markers+text",
                    fill="tozeroy",
                    fillcolor="rgba(16, 185, 129, 0.16)",
                    line=dict(color="#059669" if es_blanco_p else "#10B981", width=4, shape='spline'),
                    marker=dict(
                        size=11,
                        color=[
                            "#10B981" if "ÓPTIMA" in dg else "#F59E0B" if "ALERTA" in dg else "#EF4444"
                            for dg in df_res["Diagnóstico Gerencial"]
                        ],
                        line=dict(width=1.8, color="#0F172A" if es_blanco_p else "#FFFFFF")
                    ),
                    text=[str(v) if i % 2 == 0 else "" for i, v in enumerate(df_res['Dotación Proyectada en Vivo'])],
                    textposition="bottom center",
                    textfont=dict(size=11, color="#047857" if es_blanco_p else "#6EE7B7"),
                    customdata=df_res[['Diagnóstico Gerencial', 'Hover_Ausentes', 'Hover_Conectados']].values,
                    hovertemplate=(
                        "<b>🕒 Bloque %{x} hrs — 🟢 Conectados: %{y}</b><br>"
                        "🚦 <b>Estado:</b> %{customdata[0]}<br>"
                        "🔴 <b>Ausentes en este horario (Comuna/Domicilio):</b><br>%{customdata[1]}<br>"
                        "🟢 <b>Muestra Conectados (Comuna/Domicilio):</b><br>%{customdata[2]}"
                        "<extra></extra>"
                    )
                ))

                fig2.add_trace(go.Bar(
                    x=df_res['Hora Bloque'],
                    y=df_res['Ausencias Reales'],
                    name="🔴 Ausencias / Brecha Horaria",
                    marker_color="rgba(239, 68, 68, 0.55)",
                    text=df_res['Ausencias Reales'].apply(lambda v: f"-{v}" if v > 0 else ""),
                    textposition="outside",
                    textfont=dict(size=11, color="#B91C1C" if es_blanco_p else "#FCA5A5"),
                    customdata=df_res['Hover_Ausentes'],
                    hovertemplate="<b>🕒 %{x} hrs — 🔴 Ausentes: %{y}</b><br><b>👤 Quiénes faltan (Comuna/Domicilio):</b><br>%{customdata}<extra></extra>"
                ))

                max_y_pred = max(10, int(df_res[['Bloque FC (Plan)', 'Dotación Ideal Matemática', 'Dotación Proyectada en Vivo']].max().max()) + 9)

                fig2.update_layout(
                    template="plotly_white" if es_blanco_p else "plotly_dark",
                    height=510,
                    plot_bgcolor=bg_plot_p,
                    paper_bgcolor=bg_paper_p,
                    font=dict(color=txt_col_p, size=13),
                    legend=dict(orientation="h", yanchor="bottom", y=1.03, xanchor="right", x=1, font=dict(size=12, color=txt_col_p)),
                    xaxis=dict(title="Tramo Horario del Día (Cada 30 Minutos)", type="category", tickangle=-45, tickfont=dict(color=txt_col_p), gridcolor=grid_col_p, showgrid=True, linecolor=grid_col_p),
                    yaxis=dict(title="Ejecutivos Operativos", range=[0, max_y_pred], tickfont=dict(color=txt_col_p), gridcolor=grid_col_p, showgrid=True, linecolor=grid_col_p),
                    margin=dict(l=25, r=25, t=45, b=35),
                    hoverlabel=dict(bgcolor="#0F172A", bordercolor="#38BDF8", font=dict(color="#F8FAFC", size=12)),
                    shapes=[
                        dict(
                            type="line",
                            xref="x",
                            yref="paper",
                            x0=hora_inspeccion,
                            x1=hora_inspeccion,
                            y0=0,
                            y1=1,
                            line=dict(color="#D97706" if es_blanco_p else "#FBBF24", width=2.5, dash="dash")
                        )
                    ]
                )
                st.plotly_chart(fig2, width="stretch")

                st.markdown("##### 📑 Matriz Predictiva Hora a Hora (Bloque FC vs Ideal Matemática vs Proyección Real)")

                def style_dif_pred(v):
                    try:
                        n = int(v)
                        if n >= 0:
                            return 'color: #10B981; font-weight: bold;'
                        elif n >= -3:
                            return 'background-color: rgba(245, 158, 11, 0.22); color: #F59E0B; font-weight: bold;'
                        return 'background-color: rgba(239, 68, 68, 0.28); color: #EF4444; font-weight: bold;'
                    except Exception:
                        return ''

                def style_aus_pred(v):
                    try:
                        n = int(v)
                        if n == 0:
                            return 'color: #10B981; font-weight: bold;'
                        elif n <= 3:
                            return 'color: #F59E0B; font-weight: bold;'
                        return 'background-color: rgba(239, 68, 68, 0.25); color: #EF4444; font-weight: bold;'
                    except Exception:
                        return ''

                def style_diag_pred(v):
                    s = str(v)
                    if "ÓPTIMA" in s:
                        return 'background-color: rgba(16, 185, 129, 0.2); color: #10B981; font-weight: bold;'
                    elif "ALERTA" in s:
                        return 'background-color: rgba(245, 158, 11, 0.22); color: #F59E0B; font-weight: bold;'
                    elif "CRÍTICO" in s:
                        return 'background-color: rgba(239, 68, 68, 0.28); color: #EF4444; font-weight: bold;'
                    return 'color: #94A3B8;'

                max_p_pred = max(1, int(df_export_pred["Bloque FC (Plan)"].max()))
                styled_pred = (
                    df_export_pred.style
                    .bar(subset=["Bloque FC (Plan)"], color="#2563EB", vmin=0, vmax=max_p_pred)
                    .bar(subset=["Dotación Proyectada en Vivo"], color="#059669", vmin=0, vmax=max_p_pred)
                    .map(lambda _: 'color: #C084FC; font-weight: bold;', subset=["Dotación Ideal Matemática"])
                    .map(style_aus_pred, subset=["Ausencias Reales"])
                    .map(style_dif_pred, subset=["Diferencia vs Bloque FC"])
                    .map(style_diag_pred, subset=["Diagnóstico Gerencial"])
                    .map(lambda _: 'color: #38BDF8; font-weight: bold;', subset=["Hora Bloque"])
                )
                st.dataframe(styled_pred, width="stretch", hide_index=True, height=460)
            else:
                st.info("No hay turnos activos en parrilla para proyectar.")
        except Exception as e:
            st.error(f"Error en Cuadro Predictivo: {e}")