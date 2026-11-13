import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import duckdb
import io, os, re
from datetime import datetime, timedelta, time
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

# ==============================================================================
# FUNCIONES DE NORMALIZACIÓN Y PARSEO
# ==============================================================================
def normalizar_rut(val):
    if pd.isna(val) or val is None:
        return ""
    s = str(val).strip()
    if s.endswith(".0"):
        s = s[:-2]
    s = s.replace(".", "").replace(" ", "").upper()
    if not s or s in ['NONE', 'NAN', 'NAT', 'NULL', 'RUT', 'ACTIVOS', 'INACTIVOS', 'TOTAL', '--:--']:
        return ""
    if "-" in s:
        p = s.split("-")
        return f"{p[0]}-{p[1]}"
    if len(s) >= 2 and s[:-1].isdigit():
        return f"{s[:-1]}-{s[-1]}"
    return s

def a_hora_str(val, defecto="--:--"):
    if pd.isna(val) or val is None:
        return defecto
    if isinstance(val, time):
        if val.hour == 0 and val.minute == 0 and val.second == 0:
            return defecto
        return val.strftime("%H:%M")
    if isinstance(val, datetime):
        return val.strftime("%H:%M")
    s = str(val).strip()
    if s.upper() in ["LIBRE", "VACACIONES", "LICENCIA", "NAN", "NONE", "", "00:00:00", "00:00", "--:--"]:
        return defecto
    match = re.search(r'(\d{1,2}):(\d{2})', s)
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        if h == 0 and m == 0:
            return defecto
        return f"{h:02d}:{m:02d}"
    return defecto

def a_minutos_turno(val):
    if pd.isna(val) or val is None:
        return 99999
    if isinstance(val, time) and val.hour == 0 and val.minute == 0 and val.second == 0:
        return 99999
    if isinstance(val, (datetime, time)):
        h, m = val.hour, val.minute
    else:
        s = str(val).strip()
        if s.upper() in ["LIBRE", "VACACIONES", "LICENCIA", "NAN", "NONE", "", "00:00:00", "00:00", "--:--"]:
            return 99999
        match = re.search(r'(\d{1,2}):(\d{2})', s)
        if match:
            h, m = int(match.group(1)), int(match.group(2))
        else:
            return 99999
    if h == 0 and m == 0:
        return 99999
    if h < 7:
        h += 24
    return h * 60 + m

def detectar_col(columnas, palabras_clave, valor_defecto=None):
    for p in palabras_clave:
        for c in columnas:
            if p in str(c).lower().strip():
                return c
    return valor_defecto

def calc_fin_tiempo(h_ini, minutos):
    if h_ini in ["--:--", "00:00", "", None]: return "--:--"
    try:
        p = h_ini.split(":")
        return (datetime.combine(datetime.today(), time(int(p[0]), int(p[1]))) + timedelta(minutes=minutos)).strftime("%H:%M")
    except Exception: return "--:--"

# ==============================================================================
# MOTOR DE EXTRACCIÓN WFM (NÚCLEO ORIGINAL CON CACHÉ SIN ESCANEO _)
# ==============================================================================
@st.cache_data(show_spinner=False, max_entries=8)
def extraer_datos_base(dia_eval, version_datos, _hojas_semanales, _fechas_dict, _dict_nombres, _dict_supervisores, _dict_servicios, _dict_estados_bdd, _dict_comentarios):
    hojas_semanales = _hojas_semanales
    fechas_dict = _fechas_dict
    dict_nombres = _dict_nombres
    dict_supervisores = _dict_supervisores
    dict_servicios = _dict_servicios
    dict_estados_bdd = _dict_estados_bdd
    dict_comentarios = _dict_comentarios

    dias_nombres_es = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO", "DOMINGO"]
    dias_nombres_sin_acento = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"]
    
    filas_asistencia, filas_breaks, filas_colaciones = [], [], []
    ruts_en_malla = set()

    if dia_eval in hojas_semanales and dia_eval.upper() in dias_nombres_es + dias_nombres_sin_acento:
        df_raw = hojas_semanales[dia_eval].copy()

        for _, row in df_raw.iloc[:, :10].iterrows():
            r_c = normalizar_rut(row.iloc[0])
            n_c = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ""
            if not r_c or any(k in n_c.upper() for k in ["NOMBRE", "RUT", "TOTAL", "ACTIVOS", "INACTIVOS", "BREAK"]): continue
            
            ruts_en_malla.add(r_c)
            h_brk = a_hora_str(row.iloc[4])
            tipo_b = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else "Break 1"
            sup_b = str(row.iloc[6]).strip() if len(row) > 6 and pd.notna(row.iloc[6]) else "N/A"
            h_ent = a_hora_str(row.iloc[7])
            h_sal = a_hora_str(row.iloc[8]) if len(row) > 8 else "--:--"
            t_brk = calc_fin_tiempo(h_brk, 15)

            filas_breaks.append({"RUT": r_c, "NOMBRE": dict_nombres.get(r_c, n_c), "ESTADO": dict_estados_bdd.get(r_c, "ACTIVO"), "COMENTARIO": dict_comentarios.get(r_c, ""), "Entrada": h_ent, "Salida": h_sal, "INICIO_BREAK": h_brk, "TERMINO_BREAK": t_brk, "TIPO_BREAK": tipo_b, "SUPERVISOR": dict_supervisores.get(r_c, sup_b), "PLATAFORMA": dict_servicios.get(r_c, "FRONT"), "ORDEN_BRK": a_minutos_turno(h_brk), "ORDEN_TURNO": a_minutos_turno(h_ent)})
            filas_asistencia.append({"RUT": r_c, "NOMBRE": dict_nombres.get(r_c, n_c), "ESTADO": dict_estados_bdd.get(r_c, "ACTIVO"), "COMENTARIO": dict_comentarios.get(r_c, ""), "Entrada": h_ent, "Salida": h_sal, "SUPERVISOR": dict_supervisores.get(r_c, sup_b), "PLATAFORMA": dict_servicios.get(r_c, "FRONT"), "ORDEN_TURNO": a_minutos_turno(h_ent)})

        if df_raw.shape[1] >= 17:
            for _, row in df_raw.iloc[:, 11:20].iterrows():
                r_c = normalizar_rut(row.iloc[0])
                n_c = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ""
                if not r_c or any(k in n_c.upper() for k in ["NOMBRE", "RUT", "TOTAL", "ACTIVOS", "INACTIVOS", "DINNER"]): continue
                
                ruts_en_malla.add(r_c)
                h_out = a_hora_str(row.iloc[4])
                h_in = a_hora_str(row.iloc[5])
                
                if h_in in ["--:--", "00:00"] and h_out not in ["--:--", "00:00", "LIBRE"]:
                    h_in = calc_fin_tiempo(h_out, 30)
                    
                sup_c = str(row.iloc[7]).strip() if len(row) > 7 and pd.notna(row.iloc[7]) else "N/A"
                filas_colaciones.append({"RUT": r_c, "NOMBRE": dict_nombres.get(r_c, n_c), "ESTADO": dict_estados_bdd.get(r_c, "ACTIVO"), "COMENTARIO": dict_comentarios.get(r_c, ""), "INICIO_COLACION": h_out, "TERMINO_COLACION": h_in, "SUPERVISOR": dict_supervisores.get(r_c, sup_c), "PLATAFORMA": dict_servicios.get(r_c, "FRONT"), "ORDEN_COL": a_minutos_turno(h_out)})

    elif dia_eval in fechas_dict and "BASE CARGA" in hojas_semanales:
        df_bc_dia = hojas_semanales["BASE CARGA"][hojas_semanales["BASE CARGA"]["FECHA"] == fechas_dict[dia_eval]].copy()
        c_bc_rut = detectar_col(list(df_bc_dia.columns), ["rut"], "RUT")
        df_bc_dia["RUT"] = df_bc_dia[c_bc_rut].apply(normalizar_rut)
        df_bc_dia = df_bc_dia[df_bc_dia["RUT"] != ""].copy()
        
        ruts_en_malla.update(df_bc_dia["RUT"].tolist())

        c_bc_ent = detectar_col(list(df_bc_dia.columns), ["hora_ini", "entrada"], "HORA_INI")
        c_bc_sal = detectar_col(list(df_bc_dia.columns), ["hora_ter", "salida"], "HORA_TER")
        c_bc_bini1 = detectar_col(list(df_bc_dia.columns), ["hora_ini_break1", "break1_ini"], "HORA_INI_BREAK1")
        c_bc_bter1 = detectar_col(list(df_bc_dia.columns), ["hora_ter_break1", "break1_ter"], "HORA_TER_BREAK1")
        c_bc_bini2 = detectar_col(list(df_bc_dia.columns), ["hora_ini_break2", "break2_ini"], "HORA_INI_BREAK2")
        c_bc_bter2 = detectar_col(list(df_bc_dia.columns), ["hora_ter_break2", "break2_ter"], "HORA_TER_BREAK2")
        c_bc_cini = detectar_col(list(df_bc_dia.columns), ["cola_hora_ini", "dinner_out"], "COLA_HORA_INI")
        c_bc_cter = detectar_col(list(df_bc_dia.columns), ["cola_hora_ter", "dinner_in"], "COLA_HORA_TER")

        df_bc_dia["Entrada"] = df_bc_dia[c_bc_ent].apply(a_hora_str)
        df_bc_dia = df_bc_dia[~df_bc_dia["Entrada"].isin(["LIBRE", "VACACIONES", "LICENCIA", "--:--"])].copy()
        df_bc_dia["NOMBRE"] = df_bc_dia["RUT"].map(dict_nombres).fillna(df_bc_dia["RUT"])
        df_bc_dia["ESTADO"] = df_bc_dia["RUT"].map(dict_estados_bdd).fillna("ACTIVO")
        df_bc_dia["COMENTARIO"] = df_bc_dia["RUT"].map(dict_comentarios).fillna("")
        df_bc_dia["SUPERVISOR"] = df_bc_dia["RUT"].map(dict_supervisores).fillna("N/A")
        df_bc_dia["PLATAFORMA"] = df_bc_dia["RUT"].map(dict_servicios).fillna("FRONT")
        df_bc_dia["Salida"] = df_bc_dia[c_bc_sal].apply(a_hora_str)
        df_bc_dia["ORDEN_TURNO"] = df_bc_dia["Entrada"].apply(a_minutos_turno)

        df_asist_raw = df_bc_dia[["RUT", "NOMBRE", "ESTADO", "COMENTARIO", "Entrada", "Salida", "SUPERVISOR", "PLATAFORMA", "ORDEN_TURNO"]].copy()

        for _, r in df_bc_dia.iterrows():
            b1 = a_hora_str(r.get(c_bc_bini1))
            tb1 = a_hora_str(r.get(c_bc_bter1))
            if b1 not in ["--:--", "00:00", "LIBRE"]:
                if tb1 in ["--:--", "00:00"]: tb1 = calc_fin_tiempo(b1, 15)
                filas_breaks.append({"RUT": r["RUT"], "NOMBRE": r["NOMBRE"], "ESTADO": r["ESTADO"], "COMENTARIO": r["COMENTARIO"], "Entrada": r["Entrada"], "Salida": r["Salida"], "INICIO_BREAK": b1, "TERMINO_BREAK": tb1, "TIPO_BREAK": "Break 1", "SUPERVISOR": r["SUPERVISOR"], "PLATAFORMA": r["PLATAFORMA"], "ORDEN_BRK": a_minutos_turno(b1), "ORDEN_TURNO": r["ORDEN_TURNO"]})
            b2 = a_hora_str(r.get(c_bc_bini2)) if c_bc_bini2 else "--:--"
            tb2 = a_hora_str(r.get(c_bc_bter2)) if c_bc_bter2 else "--:--"
            if b2 not in ["--:--", "00:00", "LIBRE"]:
                if tb2 in ["--:--", "00:00"]: tb2 = calc_fin_tiempo(b2, 15)
                filas_breaks.append({"RUT": r["RUT"], "NOMBRE": r["NOMBRE"], "ESTADO": r["ESTADO"], "COMENTARIO": r["COMENTARIO"], "Entrada": r["Entrada"], "Salida": r["Salida"], "INICIO_BREAK": b2, "TERMINO_BREAK": tb2, "TIPO_BREAK": "Break 2", "SUPERVISOR": r["SUPERVISOR"], "PLATAFORMA": r["PLATAFORMA"], "ORDEN_BRK": a_minutos_turno(b2), "ORDEN_TURNO": r["ORDEN_TURNO"]})

            c_ini = a_hora_str(r.get(c_bc_cini))
            c_ter = a_hora_str(r.get(c_bc_cter))
            if c_ini not in ["--:--", "00:00", "LIBRE"]:
                if c_ter in ["--:--", "00:00"]: c_ter = calc_fin_tiempo(c_ini, 30)
                filas_colaciones.append({"RUT": r["RUT"], "NOMBRE": r["NOMBRE"], "ESTADO": r["ESTADO"], "COMENTARIO": r["COMENTARIO"], "Entrada": r["Entrada"], "Salida": r["Salida"], "INICIO_COLACION": c_ini, "TERMINO_COLACION": c_ter, "SUPERVISOR": r["SUPERVISOR"], "PLATAFORMA": r["PLATAFORMA"], "ORDEN_COL": a_minutos_turno(c_ini), "ORDEN_TURNO": r["ORDEN_TURNO"]})

        return df_asist_raw, pd.DataFrame(filas_breaks), pd.DataFrame(filas_colaciones)

    df_asist_raw = pd.DataFrame(filas_asistencia).drop_duplicates(subset=["RUT"], keep="first") if filas_asistencia else pd.DataFrame()
    df_breaks_raw = pd.DataFrame(filas_breaks) if filas_breaks else pd.DataFrame()
    df_colac_raw = pd.DataFrame(filas_colaciones) if filas_colaciones else pd.DataFrame()

    if not df_colac_raw.empty and not df_asist_raw.empty:
        map_ent = dict(zip(df_asist_raw["RUT"], df_asist_raw["Entrada"]))
        map_sal = dict(zip(df_asist_raw["RUT"], df_asist_raw["Salida"]))
        map_ord_t = dict(zip(df_asist_raw["RUT"], df_asist_raw["ORDEN_TURNO"]))
        df_colac_raw["Entrada"] = df_colac_raw["RUT"].map(map_ent).fillna("--:--")
        df_colac_raw["Salida"] = df_colac_raw["RUT"].map(map_sal).fillna("--:--")
        df_colac_raw["ORDEN_TURNO"] = df_colac_raw["RUT"].map(map_ord_t).fillna(99999)

    return df_asist_raw, df_breaks_raw, df_colac_raw

# ==============================================================================
# MOTOR EXCEL: PARRILLA HORARIA UNIFICADA Y CRONOLÓGICA + DROPDOWNS
# ==============================================================================
border_fino = Border(left=Side(style='thin', color='D0D3D4'), right=Side(style='thin', color='D0D3D4'), top=Side(style='thin', color='D0D3D4'), bottom=Side(style='thin', color='D0D3D4'))

def auto_ajustar_columnas(ws):
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            except: pass
        ws.column_dimensions[col_letter].width = min(max_len + 4, 35)

def escribir_bloques_horarios_unificados(ws, df_br, df_co, dia_str, start_row, dv_asist, dv_entre):
    br = df_br.copy() if not df_br.empty else pd.DataFrame()
    if not br.empty:
        br.rename(columns={"INICIO_BREAK": "Inicio", "TERMINO_BREAK": "Término", "TIPO_BREAK": "Tipo Actividad"}, inplace=True)
        
    co = df_co.copy() if not df_co.empty else pd.DataFrame()
    if not co.empty:
        co.rename(columns={"INICIO_COLACION": "Inicio", "TERMINO_COLACION": "Término"}, inplace=True)
        co["Tipo Actividad"] = "Colación"
        
    if br.empty and co.empty: return start_row
    
    df_valid = pd.concat([br, co], ignore_index=True)
    df_valid = df_valid[~df_valid["Inicio"].isin(["--:--", "00:00", "", None])].copy()
    if df_valid.empty: return start_row
    
    df_valid.rename(columns={"NOMBRE": "Nombre Ejecutivo"}, inplace=True, errors="ignore")
    
    df_valid["ORDEN"] = df_valid["Inicio"].apply(a_minutos_turno)
    df_valid.sort_values(by=["ORDEN", "Tipo Actividad", "Nombre Ejecutivo"], inplace=True)
    
    current_row = start_row
    bloques_unicos = df_valid["Inicio"].unique()
    cols_export = ["RUT", "Nombre Ejecutivo", "ESTADO", "COMENTARIO", "DÍA", "Entrada", "Salida", "Inicio", "Término", "Tipo Actividad", "Supervisor", "Servicio", "Asistencia", "Entregado"]
    
    for hora_actual in bloques_unicos:
        df_bloque = df_valid[df_valid["Inicio"] == hora_actual]
        
        titulo = f"🕒 PARRILLA HORARIA — BLOQUE {hora_actual}"
        ws.cell(row=current_row, column=1, value=titulo)
        ws.cell(row=current_row, column=1).font = Font(bold=True, size=14, color="000000")
        current_row += 1
        
        for col_i, col_name in enumerate(cols_export, 1):
            c = ws.cell(row=current_row, column=col_i, value=col_name)
            if col_name in ["Inicio", "Término"]: bg = "2563EB"
            elif col_name in ["Asistencia", "Entregado"]: bg = "0F766E"
            else: bg = "1E293B"
                
            c.fill = PatternFill("solid", fgColor=bg)
            c.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = border_fino
            
        current_row += 1
        
        for _, r in df_bloque.iterrows():
            for col_i, col_name in enumerate(cols_export, 1):
                if col_name in ["Asistencia", "Entregado"]: val = ""
                elif col_name == "DÍA": val = dia_str.split('(')[0].strip() if '(' in dia_str else dia_str
                elif col_name == "Supervisor": val = r.get("SUPERVISOR", "--:--")
                elif col_name == "Servicio": val = r.get("PLATAFORMA", "--:--")
                else: val = r.get(col_name, "--:--")
                    
                c = ws.cell(row=current_row, column=col_i, value=val)
                c.border = border_fino
                c.alignment = Alignment(horizontal="center", vertical="center")
                
                if col_name == "Tipo Actividad":
                    if "Break" in str(val):
                        c.fill = PatternFill("solid", fgColor="FEF3C7")
                        c.font = Font(color="D97706", bold=True)
                    elif "Colación" in str(val):
                        c.fill = PatternFill("solid", fgColor="D1FAE5")
                        c.font = Font(color="059669", bold=True)
                        
                if col_name == "Asistencia": dv_asist.add(c)
                elif col_name == "Entregado": dv_entre.add(c)
                
            current_row += 1
        current_row += 2
        
    return current_row

def generar_excel_dia_semana_bloques(dia_str, df_br, df_co):
    output = io.BytesIO()
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    
    dv_asist = DataValidation(type="list", formula1='"PRESENTE,AUSENTE"', allow_blank=True)
    dv_entre = DataValidation(type="list", formula1='"SI,NO"', allow_blank=True)
    dv_asist.error = "Selecciona PRESENTE o AUSENTE"
    dv_entre.error = "Selecciona SI o NO"
    
    ws_bc = wb.create_sheet("Parrilla_Horaria")
    ws_bc.add_data_validation(dv_asist)
    ws_bc.add_data_validation(dv_entre)
    escribir_bloques_horarios_unificados(ws_bc, df_br, df_co, dia_str, 1, dv_asist, dv_entre)
    auto_ajustar_columnas(ws_bc)
    
    wb.save(output)
    return output.getvalue()

# ==============================================================================
# MÓDULO PRINCIPAL CONSOLA WFM
# ==============================================================================
def renderizar_modulo_colaciones_asistencia(con, fecha_activa_str):
    st.markdown("""
    <style>
        .header-section-break {
            background: linear-gradient(90deg, rgba(217, 119, 6, 0.25) 0%, rgba(15, 23, 42, 0.85) 100%);
            border-left: 5px solid #FBBF24;
            padding: 10px 16px;
            border-radius: 8px;
            margin: 24px 0 10px 0;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .header-section-colac {
            background: linear-gradient(90deg, rgba(16, 185, 129, 0.25) 0%, rgba(15, 23, 42, 0.85) 100%);
            border-left: 5px solid #34D399;
            padding: 10px 16px;
            border-radius: 8px;
            margin: 24px 0 10px 0;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
    </style>
    """, unsafe_allow_html=True)

    con.execute("CREATE TABLE IF NOT EXISTS control_asistencia_manual (fecha VARCHAR, rut VARCHAR, asistencia VARCHAR, PRIMARY KEY (fecha, rut));")
    con.execute("CREATE TABLE IF NOT EXISTS control_entregas_dia (fecha VARCHAR, rut VARCHAR, tipo VARCHAR, entregado BOOLEAN, hora_marca VARCHAR, PRIMARY KEY (fecha, rut, tipo));")
    con.execute("CREATE TABLE IF NOT EXISTS maestro_bdd_personal (rut VARCHAR PRIMARY KEY, nombre VARCHAR, supervisor VARCHAR, plataforma VARCHAR, estado VARCHAR, motivo VARCHAR);")
    con.execute("CREATE TABLE IF NOT EXISTS control_estado_personal (rut VARCHAR PRIMARY KEY, estado_forzado VARCHAR, comentario VARCHAR);")

    hojas_semanales = st.session_state.get("excel_colaciones_hojas", {})
    if not hojas_semanales:
        st.warning("⚠️ Faltan datos operativos. Ve a la pestaña 'Ingesta de Datos' y sube la Malla Semanal (Excel).")
        return

    count_bdd = con.execute("SELECT count(*) FROM maestro_bdd_personal").fetchone()[0]
    
    hoja_bdd_match = next((s for s in hojas_semanales.keys() if any(kw in s.upper() for kw in ["CLIENTE FINAL", "BBDD", "BDD", "BASE DATOS", "MAESTRO"])), None)
    if not hoja_bdd_match and len(hojas_semanales) > 0:
        hoja_bdd_match = list(hojas_semanales.keys())[0]

    if hoja_bdd_match and count_bdd == 0:
        df_bdd_in = hojas_semanales[hoja_bdd_match]
        c_brut = detectar_col(list(df_bdd_in.columns), ["rut"], df_bdd_in.columns[0])
        c_bnom = detectar_col(list(df_bdd_in.columns), ["nombre eac", "nombres", "nombre", "ejecutivo"], None)
        c_bsup = detectar_col(list(df_bdd_in.columns), ["nombre supervisor", "supervisor"], None)
        c_bplat = detectar_col(list(df_bdd_in.columns), ["plataforma", "servicio", "canal"], None)
        c_best = detectar_col(list(df_bdd_in.columns), ["estado", "estado operacional"], None)
        c_bmot = detectar_col(list(df_bdd_in.columns), ["motivo inactividad", "motivo"], None)

        registros_bdd = []
        for _, fila_b in df_bdd_in.iterrows():
            r_limpio = normalizar_rut(fila_b.get(c_brut))
            if r_limpio:
                nom_ag = str(fila_b.get(c_bnom)).strip() if c_bnom and pd.notna(fila_b.get(c_bnom)) else r_limpio
                sup_ag = str(fila_b.get(c_bsup)).strip() if c_bsup and pd.notna(fila_b.get(c_bsup)) else "N/A"
                plat_raw = str(fila_b.get(c_bplat)).strip().upper() if c_bplat and pd.notna(fila_b.get(c_bplat)) else "FRONT"
                
                if "WHATSAPP" in plat_raw: plat_final = "WHATSAPP"
                elif "COMERCIAL" in plat_raw: plat_final = "COMERCIAL"
                elif "WEB" in plat_raw: plat_final = "WEB"
                elif any(k in plat_raw for k in ["PCE", "BACKOFFICE", "BACK"]): plat_final = "PCE / BACK"
                elif "RRSS" in plat_raw: plat_final = "RRSS"
                else: plat_final = "FRONT"

                est_ag = str(fila_b.get(c_best)).strip().upper() if c_best and pd.notna(fila_b.get(c_best)) else "ACTIVO"
                mot_ag = str(fila_b.get(c_bmot)).strip().upper() if c_bmot and pd.notna(fila_b.get(c_bmot)) else est_ag
                
                if est_ag == "BAJA" and mot_ag != "BAJA": est_ag = mot_ag
                elif est_ag == "INACTIVO": est_ag = mot_ag
                
                registros_bdd.append((r_limpio, nom_ag, sup_ag, plat_final, est_ag, mot_ag))

        if registros_bdd:
            df_to_db = pd.DataFrame(registros_bdd, columns=["rut", "nombre", "supervisor", "plataforma", "estado", "motivo"]).drop_duplicates(subset=["rut"], keep="first")
            con.execute("DELETE FROM maestro_bdd_personal")
            con.register("df_to_db", df_to_db)
            con.execute("INSERT INTO maestro_bdd_personal SELECT * FROM df_to_db")
            con.unregister("df_to_db")

    ruts_conectados = set()
    try:
        hay_ll = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'datos_login_logout'").fetchone()[0] > 0
        if hay_ll:
            df_ll = con.execute(f"SELECT * FROM datos_login_logout WHERE fecha_gestion = '{fecha_activa_str}'").df()
            if not df_ll.empty:
                c_rut_ll = detectar_col(list(df_ll.columns), ["login_id", "rut", "cedula", "agent", "identificador", "id_usuario", "login id", "id login"], df_ll.columns[0])
                ruts_conectados = set(df_ll[c_rut_ll].apply(normalizar_rut).dropna().unique())
    except Exception: pass

    c_limp1, c_limp2 = st.columns([3, 1])
    if c_limp2.button("🧹 Borrar Caché y Liberar Memoria", use_container_width=True):
        st.cache_data.clear()
        for key in list(st.session_state.keys()): del st.session_state[key]
        con.execute("DELETE FROM maestro_bdd_personal")
        con.execute("DELETE FROM control_asistencia_manual")
        con.execute("DELETE FROM control_entregas_dia")
        con.execute("DELETE FROM control_estado_personal")
        st.success("✅ Caché y Base de Datos limpiadas exitosamente.")
        st.rerun()

    dias_nombres_es = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO", "DOMINGO"]
    dias_nombres_sin_acento = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"]

    db_maestro = con.execute("""
        SELECT 
            m.rut, 
            m.nombre, 
            m.supervisor, 
            m.plataforma, 
            COALESCE(c.estado_forzado, m.estado) as estado,
            COALESCE(c.comentario, '') as comentario
        FROM maestro_bdd_personal m
        LEFT JOIN control_estado_personal c ON m.rut = c.rut
    """).df()
    
    dict_nombres = dict(zip(db_maestro["rut"], db_maestro["nombre"])) if not db_maestro.empty else {}
    dict_supervisores = dict(zip(db_maestro["rut"], db_maestro["supervisor"])) if not db_maestro.empty else {}
    dict_servicios = dict(zip(db_maestro["rut"], db_maestro["plataforma"])) if not db_maestro.empty else {}
    dict_estados_bdd = dict(zip(db_maestro["rut"], db_maestro["estado"])) if not db_maestro.empty else {}
    dict_comentarios = dict(zip(db_maestro["rut"], db_maestro["comentario"])) if not db_maestro.empty else {}

    ahora_dt = datetime.now()
    nombre_dia_hoy = dias_nombres_es[ahora_dt.weekday()]
    fecha_hoy_iso = ahora_dt.strftime("%Y-%m-%d")

    hojas_dias_directas = [s for s in hojas_semanales.keys() if s.upper() in dias_nombres_es + dias_nombres_sin_acento]
    fechas_dict = {}
    tiene_base_carga = "BASE CARGA" in hojas_semanales

    if hojas_dias_directas: opciones_dias = hojas_dias_directas
    elif tiene_base_carga:
        df_bc_raw = hojas_semanales["BASE CARGA"].copy()
        for f_val in df_bc_raw["FECHA"].dropna().unique():
            try:
                dt = pd.to_datetime(f_val)
                fechas_dict[f"{dias_nombres_es[dt.weekday()]} ({dt.strftime('%Y-%m-%d')})"] = f_val
            except Exception:
                fechas_dict[f"DÍA ({str(f_val)[:10]})"] = f_val
        opciones_dias = list(fechas_dict.keys())
    else: opciones_dias = ["Visualización de Nómina BDD"]

    idx_dia_auto = 0
    hoy_norm = nombre_dia_hoy.replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U")

    if opciones_dias != ["Visualización de Nómina BDD"]:
        for i, opc in enumerate(opciones_dias):
            if hoy_norm in str(opc).upper().replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U") or fecha_hoy_iso in str(opc):
                idx_dia_auto = i
                break

    if "sel_dia_semana_wfm" not in st.session_state or st.session_state["sel_dia_semana_wfm"] not in opciones_dias:
        st.session_state["sel_dia_semana_wfm"] = opciones_dias[idx_dia_auto]

    servicios_base = ["FRONT", "COMERCIAL", "WEB", "WHATSAPP", "PCE / BACK", "RRSS", "TODOS"]

    c_sel1, c_sel2 = st.columns([2.5, 1.5])
    dia_seleccionado = c_sel1.selectbox("📅 Selecciona el día de la semana:", opciones_dias, key="sel_dia_semana_wfm")
    servicio_seleccionado = c_sel2.selectbox("🏢 Segmentar por Servicio / Canal:", servicios_base, index=0)

    version_datos = st.session_state.get("version_datos", 1)
    df_asist_raw, df_breaks_raw, df_colac_raw = extraer_datos_base(
        dia_seleccionado, version_datos, hojas_semanales, fechas_dict,
        dict_nombres, dict_supervisores, dict_servicios, dict_estados_bdd, dict_comentarios
    )

    df_breaks_raw = df_breaks_raw.copy()
    df_colac_raw = df_colac_raw.copy()

    if servicio_seleccionado != "TODOS":
        if not df_breaks_raw.empty: df_breaks_raw = df_breaks_raw[df_breaks_raw["PLATAFORMA"] == servicio_seleccionado].copy()
        if not df_colac_raw.empty: df_colac_raw = df_colac_raw[df_colac_raw["PLATAFORMA"] == servicio_seleccionado].copy()

    df_base_breaks = df_breaks_raw.sort_values(by=["ORDEN_BRK", "ORDEN_TURNO", "NOMBRE"]).reset_index(drop=True) if not df_breaks_raw.empty else pd.DataFrame()
    if not df_base_breaks.empty:
        es_activo_brk = df_base_breaks["ESTADO"].str.upper().str.contains("ACTIV", na=False)
        df_base_breaks = df_base_breaks[es_activo_brk].copy().reset_index(drop=True)

    df_base_colaciones = df_colac_raw.sort_values(by=["ORDEN_COL", "ORDEN_TURNO", "NOMBRE"]).reset_index(drop=True) if not df_colac_raw.empty else pd.DataFrame()
    if not df_base_colaciones.empty:
        es_activo_col = df_base_colaciones["ESTADO"].str.upper().str.contains("ACTIV", na=False)
        df_base_colaciones = df_base_colaciones[es_activo_col].copy().reset_index(drop=True)

    sync_rev = st.session_state.get("wfm_sync_version", 0)
    ed_key_brk = f"ed_brk_wfm_{dia_seleccionado}_{servicio_seleccionado}_{sync_rev}"
    ed_key_col = f"ed_col_wfm_{dia_seleccionado}_{servicio_seleccionado}_{sync_rev}"
    
    h_marca = datetime.now().strftime("%H:%M:%S")
    hubo_cambios = False

    if ed_key_brk in st.session_state and "edited_rows" in st.session_state[ed_key_brk]:
        edits = st.session_state[ed_key_brk]["edited_rows"]
        if edits:
            for idx_row, cambios in edits.items():
                if int(idx_row) < len(df_base_breaks):
                    rut_ag = df_base_breaks.iloc[int(idx_row)]["RUT"]
                    if "Break Entregado" in cambios:
                        con.execute(f"INSERT OR REPLACE INTO control_entregas_dia VALUES ('{fecha_activa_str}', '{rut_ag}', 'BREAK', {bool(cambios['Break Entregado'])}, '{h_marca}')")
                        hubo_cambios = True

    if ed_key_col in st.session_state and "edited_rows" in st.session_state[ed_key_col]:
        edits = st.session_state[ed_key_col]["edited_rows"]
        if edits:
            for idx_row, cambios in edits.items():
                if int(idx_row) < len(df_base_colaciones):
                    rut_ag = df_base_colaciones.iloc[int(idx_row)]["RUT"]
                    if "Colación Entregada" in cambios:
                        con.execute(f"INSERT OR REPLACE INTO control_entregas_dia VALUES ('{fecha_activa_str}', '{rut_ag}', 'COLACION', {bool(cambios['Colación Entregada'])}, '{h_marca}')")
                        hubo_cambios = True

    if hubo_cambios:
        st.session_state["wfm_sync_version"] = sync_rev + 1
        st.rerun()

    asist_db = con.execute(f"SELECT rut, asistencia FROM control_asistencia_manual WHERE fecha = '{fecha_activa_str}'").df()
    map_asist = dict(zip(asist_db["rut"], asist_db["asistencia"])) if not asist_db.empty else {}

    entregas_db = con.execute(f"SELECT rut, tipo, entregado FROM control_entregas_dia WHERE fecha = '{fecha_activa_str}'").df()
    m_brk = {r["rut"]: bool(r["entregado"]) for _, r in entregas_db[entregas_db["tipo"] == "BREAK"].iterrows()} if not entregas_db.empty else {}
    m_col = {r["rut"]: bool(r["entregado"]) for _, r in entregas_db[entregas_db["tipo"] == "COLACION"].iterrows()} if not entregas_db.empty else {}

    def obtener_asist(r_rut):
        if r_rut in map_asist: return map_asist[r_rut]
        if ruts_conectados: return "presente" if r_rut in ruts_conectados else "ausente"
        return "ausente"

    if not df_base_breaks.empty:
        df_base_breaks["Asistencia"] = df_base_breaks["RUT"].apply(obtener_asist)
        df_base_breaks["Presente"] = df_base_breaks["Asistencia"] == "presente"
        df_base_breaks["Break Entregado"] = df_base_breaks["RUT"].map(m_brk).fillna(False)

    if not df_base_colaciones.empty:
        df_base_colaciones["Asistencia"] = df_base_colaciones["RUT"].apply(obtener_asist)
        df_base_colaciones["Presente"] = df_base_colaciones["Asistencia"] == "presente"
        df_base_colaciones["Colación Entregada"] = df_base_colaciones["RUT"].map(m_col).fillna(False)

    df_vista_breaks = df_base_breaks[["RUT", "NOMBRE", "Presente", "ESTADO", "COMENTARIO", "Entrada", "Salida", "INICIO_BREAK", "TERMINO_BREAK", "TIPO_BREAK", "SUPERVISOR", "PLATAFORMA", "Break Entregado"]] if not df_base_breaks.empty else pd.DataFrame()
    df_vista_colaciones = df_base_colaciones[["RUT", "NOMBRE", "Presente", "ESTADO", "COMENTARIO", "Entrada", "Salida", "INICIO_COLACION", "TERMINO_COLACION", "SUPERVISOR", "PLATAFORMA", "Colación Entregada"]] if not df_base_colaciones.empty else pd.DataFrame()

    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%); border: 1px solid #334155; border-radius: 12px; padding: 18px 24px; margin-bottom: 20px;">
        <div style="font-size: 0.8rem; letter-spacing: 0.08em; color: #94A3B8; text-transform: uppercase;">
            Consola WFM &bull; {dia_seleccionado} &bull; {servicio_seleccionado}
        </div>
        <div style="font-size: 1.65rem; font-weight: 800; color: #F8FAFC; margin-top: 2px;">
            Planificación Break y Colaciones
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### 📥 Descarga de Planillas en Excel")
    c_btn_exp1, c_btn_exp2 = st.columns(2)

    c_btn_exp1.download_button(
        label=f"📊 Exportar Planilla por Día ({dia_seleccionado})",
        data=generar_excel_dia_semana_bloques(dia_seleccionado, df_vista_breaks, df_vista_colaciones),
        file_name=f"planificacion_dia_{str(dia_seleccionado).lower().replace(' ', '_')}_{servicio_seleccionado.lower()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

    def generar_excel_semana():
        output = io.BytesIO()
        wb = openpyxl.Workbook()
        wb.remove(wb.active) 
        
        dv_asist = DataValidation(type="list", formula1='"PRESENTE,AUSENTE"', allow_blank=True)
        dv_entre = DataValidation(type="list", formula1='"SI,NO"', allow_blank=True)
        dv_asist.error = "Selecciona PRESENTE o AUSENTE"
        dv_entre.error = "Selecciona SI o NO"
        
        hay_datos = False
        for d in opciones_dias:
            if d == "Visualización de Nómina BDD": continue
            _, br_r, co_r = extraer_datos_base(d, version_datos, hojas_semanales, fechas_dict, dict_nombres, dict_supervisores, dict_servicios, dict_estados_bdd, dict_comentarios)
            
            if servicio_seleccionado != "TODOS":
                br_r = br_r[br_r["PLATAFORMA"] == servicio_seleccionado] if not br_r.empty else br_r
                co_r = co_r[co_r["PLATAFORMA"] == servicio_seleccionado] if not co_r.empty else co_r

            df_b = br_r[br_r["ESTADO"].str.upper().str.contains("ACTIV", na=False)].copy() if not br_r.empty else pd.DataFrame()
            df_c = co_r[co_r["ESTADO"].str.upper().str.contains("ACTIV", na=False)].copy() if not co_r.empty else pd.DataFrame()

            if not df_b.empty or not df_c.empty:
                hay_datos = True
                sheet_title = str(d).split('(')[0].strip().replace('/', '-')[:31]
                ws = wb.create_sheet(title=sheet_title)
                
                ws.add_data_validation(dv_asist)
                ws.add_data_validation(dv_entre)
                
                escribir_bloques_horarios_unificados(ws, df_b, df_c, d, 1, dv_asist, dv_entre)
                auto_ajustar_columnas(ws)

        if not hay_datos:
            ws = wb.create_sheet("Sin Datos")
            ws.append([f"No hay turnos registrados en la semana para {servicio_seleccionado}"])
            
        wb.save(output)
        return output.getvalue()

    c_btn_exp2.download_button(
        label=f"📅 Exportar Planilla por Semana ({servicio_seleccionado})",
        data=generar_excel_semana(),
        file_name=f"planificacion_semanal_{servicio_seleccionado.lower()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
    st.markdown("---")

    st.markdown("""
    <div class="header-section-break">
        <div>
            <span style="font-size: 1.15rem; font-weight: 800; color: #FBBF24;">☕ Control Break</span>
            <span style="font-size: 0.85rem; color: #94A3B8; margin-left: 10px;">— Orden cronológico según hora de inicio de pausa matutina</span>
        </div>
        <span style="background: rgba(245, 158, 11, 0.2); color: #FBBF24; padding: 3px 10px; border-radius: 6px; font-size: 0.75rem; font-weight: 700;">PAUSA 15 MIN</span>
    </div>
    """, unsafe_allow_html=True)

    c_br1, c_br2, c_br3, c_br4 = st.columns([2.5, 1.5, 1.2, 1.2])
    q_brk = c_br1.text_input("🔍 Buscar ejecutivo en Breaks:", key=f"src_brk_{dia_seleccionado}")
    horas_brk = ["TODAS"] + sorted(list(set([h for h in df_vista_breaks["INICIO_BREAK"].unique() if h not in ["--:--", "00:00", "LIBRE"]])), key=a_minutos_turno) if not df_vista_breaks.empty else ["TODAS"]
    fh_brk = c_br2.selectbox("⏰ Hora Break:", horas_brk, key=f"fh_brk_{dia_seleccionado}")

    df_br_flt = df_vista_breaks.copy() if not df_vista_breaks.empty else pd.DataFrame()
    if not df_br_flt.empty:
        if q_brk.strip():
            txt = q_brk.strip().upper()
            df_br_flt = df_br_flt[df_br_flt["NOMBRE"].str.upper().str.contains(txt) | df_br_flt["RUT"].str.upper().str.contains(txt)]
        if fh_brk != "TODAS":
            df_br_flt = df_br_flt[df_br_flt["INICIO_BREAK"] == fh_brk]

    if c_br3.button("☕ Entregar Todos", key=f"btn_marcar_brk_{dia_seleccionado}", use_container_width=True):
        if not df_br_flt.empty:
            for _, r in df_br_flt.iterrows():
                con.execute(f"INSERT OR REPLACE INTO control_entregas_dia VALUES ('{fecha_activa_str}', '{r['RUT']}', 'BREAK', true, '{h_marca}')")
            st.session_state["wfm_sync_version"] = sync_rev + 1
            st.rerun()

    if c_br4.button("❌ Desmarcar", key=f"btn_desmarcar_brk_{dia_seleccionado}", use_container_width=True):
        if not df_br_flt.empty:
            for _, r in df_br_flt.iterrows():
                con.execute(f"INSERT OR REPLACE INTO control_entregas_dia VALUES ('{fecha_activa_str}', '{r['RUT']}', 'BREAK', false, '{h_marca}')")
            st.session_state["wfm_sync_version"] = sync_rev + 1
            st.rerun()

    editor_brk = st.data_editor(
        df_br_flt,
        column_config={
            "RUT": st.column_config.TextColumn("RUT"),
            "NOMBRE": st.column_config.TextColumn("Nombre"),
            "Presente": st.column_config.CheckboxColumn("✅ Presente", default=False, disabled=True), 
            "ESTADO": st.column_config.TextColumn("Estado"),
            "COMENTARIO": None,
            "Entrada": st.column_config.TextColumn("Entrada"),
            "Salida": st.column_config.TextColumn("Salida"),
            "INICIO_BREAK": st.column_config.TextColumn("⏰ Inicio Break"),
            "TERMINO_BREAK": st.column_config.TextColumn("⏰ Término Break"),
            "TIPO_BREAK": None, 
            "SUPERVISOR": st.column_config.TextColumn("Supervisor"),
            "PLATAFORMA": st.column_config.TextColumn("Servicio"),
            "Break Entregado": st.column_config.CheckboxColumn("☕ Break Entregado", default=False),
        },
        disabled=["RUT", "NOMBRE", "ESTADO", "Entrada", "Salida", "INICIO_BREAK", "TERMINO_BREAK", "SUPERVISOR", "PLATAFORMA"],
        hide_index=True,
        use_container_width=True,
        key=ed_key_brk
    )

    st.markdown("""
    <div class="header-section-colac">
        <div>
            <span style="font-size: 1.15rem; font-weight: 800; color: #34D399;">🍽️ Control Colaciones</span>
            <span style="font-size: 0.85rem; color: #94A3B8; margin-left: 10px;">— Orden cronológico según inicio de almuerzo / dinner</span>
        </div>
        <span style="background: rgba(16, 185, 129, 0.2); color: #34D399; padding: 3px 10px; border-radius: 6px; font-size: 0.75rem; font-weight: 700;">ALMUERZO / DINNER</span>
    </div>
    """, unsafe_allow_html=True)

    c_cl1, c_cl2, c_cl3, c_cl4 = st.columns([2.5, 1.5, 1.2, 1.2])
    q_col = c_cl1.text_input("🔍 Buscar ejecutivo en Colaciones:", key=f"src_col_{dia_seleccionado}")
    horas_col = ["TODAS"] + sorted(list(set([h for h in df_vista_colaciones["INICIO_COLACION"].unique() if h not in ["--:--", "00:00", "LIBRE"]])), key=a_minutos_turno) if not df_vista_colaciones.empty else ["TODAS"]
    fh_col = c_cl2.selectbox("⏰ Hora Colación:", horas_col, key=f"fh_col_{dia_seleccionado}")

    c_chk_col, _ = st.columns([2.5, 2.5])
    ocultar_sin_col = c_chk_col.checkbox("Ocultar ejecutivos sin colación programada (--:-- / Turnos 5h)", value=True, key=f"chk_sin_col_{dia_seleccionado}")

    df_cl_flt = df_vista_colaciones.copy() if not df_vista_colaciones.empty else pd.DataFrame()
    if not df_cl_flt.empty:
        if ocultar_sin_col:
            df_cl_flt = df_cl_flt[~df_cl_flt["INICIO_COLACION"].isin(["--:--", "00:00", "LIBRE"])].copy()

        if q_col.strip():
            txt = q_col.strip().upper()
            df_cl_flt = df_cl_flt[df_cl_flt["NOMBRE"].str.upper().str.contains(txt) | df_cl_flt["RUT"].str.upper().str.contains(txt)]
        if fh_col != "TODAS":
            df_cl_flt = df_cl_flt[df_cl_flt["INICIO_COLACION"] == fh_col]

    if c_cl3.button("🍱 Entregar Todas", key=f"btn_marcar_col_{dia_seleccionado}", use_container_width=True):
        if not df_cl_flt.empty:
            for _, r in df_cl_flt.iterrows():
                con.execute(f"INSERT OR REPLACE INTO control_entregas_dia VALUES ('{fecha_activa_str}', '{r['RUT']}', 'COLACION', true, '{h_marca}')")
            st.session_state["wfm_sync_version"] = sync_rev + 1
            st.rerun()

    if c_cl4.button("❌ Desmarcar", key=f"btn_desmarcar_col_{dia_seleccionado}", use_container_width=True):
        if not df_cl_flt.empty:
            for _, r in df_cl_flt.iterrows():
                con.execute(f"INSERT OR REPLACE INTO control_entregas_dia VALUES ('{fecha_activa_str}', '{r['RUT']}', 'COLACION', false, '{h_marca}')")
            st.session_state["wfm_sync_version"] = sync_rev + 1
            st.rerun()

    editor_col = st.data_editor(
        df_cl_flt,
        column_config={
            "RUT": st.column_config.TextColumn("RUT"),
            "NOMBRE": st.column_config.TextColumn("Nombre"),
            "Presente": st.column_config.CheckboxColumn("✅ Presente", default=False, disabled=True),
            "ESTADO": st.column_config.TextColumn("Estado"),
            "COMENTARIO": None,
            "Entrada": st.column_config.TextColumn("Entrada"),
            "Salida": st.column_config.TextColumn("Salida"),
            "INICIO_COLACION": st.column_config.TextColumn("🍽️ Inicio Colación"),
            "TERMINO_COLACION": st.column_config.TextColumn("🍽️ Término Colación"),
            "SUPERVISOR": st.column_config.TextColumn("Supervisor"),
            "PLATAFORMA": st.column_config.TextColumn("Servicio"),
            "Colación Entregada": st.column_config.CheckboxColumn("🍱 Colación Entregada", default=False),
        },
        disabled=["RUT", "NOMBRE", "ESTADO", "Entrada", "Salida", "INICIO_COLACION", "TERMINO_COLACION", "SUPERVISOR", "PLATAFORMA"],
        hide_index=True,
        use_container_width=True,
        key=ed_key_col
    )

    col_btn_guardar, _ = st.columns([2, 3])
    if col_btn_guardar.button("💾 Guardar y Actualizar Consola", use_container_width=True, key=f"btn_g_all_v29_{dia_seleccionado}_{servicio_seleccionado}"):
        h_now = datetime.now().strftime("%H:%M:%S")
        if not df_br_flt.empty:
            for _, r in editor_brk.iterrows():
                r_rut = r["RUT"]
                con.execute(f"INSERT OR REPLACE INTO control_entregas_dia VALUES ('{fecha_activa_str}', '{r_rut}', 'BREAK', {bool(r['Break Entregado'])}, '{h_now}')")

        if not df_cl_flt.empty:
            for _, r in editor_col.iterrows():
                r_rut = r["RUT"]
                con.execute(f"INSERT OR REPLACE INTO control_entregas_dia VALUES ('{fecha_activa_str}', '{r_rut}', 'COLACION', {bool(r['Colación Entregada'])}, '{h_now}')")

        st.session_state["wfm_sync_version"] = sync_rev + 1
        st.success("✅ Entregas sincronizadas correctamente.")
        st.rerun()