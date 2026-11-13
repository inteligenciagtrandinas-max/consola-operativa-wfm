import streamlit as st
import pandas as pd
import hashlib
import calendar
import io
from datetime import datetime, date
import numpy as np
import plotly.graph_objects as go

# ==============================================================================
# COORDENADAS REALES DE COMUNAS DE LA REGIÓN METROPOLITANA
# ==============================================================================
COORDENADAS_RM = {
    "SANTIAGO": (-33.4489, -70.6693),
    "PROVIDENCIA": (-33.4314, -70.6093),
    "LAS CONDES": (-33.4117, -70.5802),
    "MAIPU": (-33.5111, -70.7581),
    "MAIPÚ": (-33.5111, -70.7581),
    "PUENTE ALTO": (-33.6117, -70.5758),
    "LA FLORIDA": (-33.5227, -70.5983),
    "ÑUÑOA": (-33.4569, -70.5976),
    "NUNOA": (-33.4569, -70.5976),
    "SAN BERNARDO": (-33.5922, -70.7044),
    "PUDAHUEL": (-33.4425, -70.7628),
    "PEÑALOLEN": (-33.4711, -70.5317),
    "PEÑALOLÉN": (-33.4711, -70.5317),
    "PENALOLEN": (-33.4711, -70.5317),
    "QUILICURA": (-33.3644, -70.7292),
    "RENCA": (-33.4039, -70.7103),
    "ESTACION CENTRAL": (-33.4617, -70.6975),
    "ESTACIÓN CENTRAL": (-33.4617, -70.6975),
    "INDEPENDENCIA": (-33.4167, -70.6500),
    "RECOLETA": (-33.4064, -70.6439),
    "MACUL": (-33.4833, -70.5833),
    "SAN MIGUEL": (-33.4917, -70.6500),
    "QUINTA NORMAL": (-33.4333, -70.6833),
    "LA CISTERNA": (-33.5333, -70.6667),
    "EL BOSQUE": (-33.5667, -70.6667),
    "HUECHURABA": (-33.3764, -70.6306),
    "LO BARNECHEA": (-33.3500, -70.5167),
    "CERRO NAVIA": (-33.4217, -70.7381),
    "LA PINTANA": (-33.5833, -70.6333),
    "CONCHALI": (-33.3833, -70.6833),
    "CONCHALÍ": (-33.3833, -70.6833),
    "LA REINA": (-33.4500, -70.5333),
    "VITACURA": (-33.3833, -70.6000),
    "SAN JOAQUIN": (-33.4833, -70.6167),
    "SAN JOAQUÍN": (-33.4833, -70.6167),
    "PEDRO AGUIRRE CERDA": (-33.4833, -70.6833),
    "PAC": (-33.4833, -70.6833),
    "LO PRADO": (-33.4500, -70.7167),
    "CERRILLOS": (-33.5000, -70.7167),
    "PADRE HURTADO": (-33.5667, -70.8167),
    "SAN RAMON": (-33.5417, -70.6417),
    "SAN RAMÓN": (-33.5417, -70.6417),
    "LA GRANJA": (-33.5333, -70.6167),
    "LO ESPEJO": (-33.5222, -70.6917),
    "COLINA": (-33.2000, -70.6667),
    "LAMPA": (-33.2833, -70.8667),
    "BUIN": (-33.7333, -70.7500),
    "PAINE": (-33.8167, -70.7500),
    "PEÑAFLOR": (-33.6061, -70.8769),
    "PENAFLOR": (-33.6061, -70.8769),
    "TALAGANTE": (-33.6667, -70.9333),
    "MELIPILLA": (-33.6833, -71.2167)
}

# ==============================================================================
# PALETA DE COLORES ÚNICOS DE ALTO CONTRASTE POR COMUNA
# ==============================================================================
PALETA_COMUNAS_RM = {
    "SANTIAGO": (220, 38, 38, "#DC2626"),
    "PUENTE ALTO": (37, 99, 235, "#2563EB"),
    "MAIPU": (22, 163, 74, "#16A34A"),
    "MAIPÚ": (22, 163, 74, "#16A34A"),
    "LA FLORIDA": (147, 51, 234, "#9333EA"),
    "ÑUÑOA": (234, 88, 12, "#EA580C"),
    "NUNOA": (234, 88, 12, "#EA580C"),
    "SAN BERNARDO": (8, 145, 178, "#0891B2"),
    "PROVIDENCIA": (219, 39, 119, "#DB2777"),
    "LAS CONDES": (79, 70, 229, "#4F46E5"),
    "PUDAHUEL": (202, 138, 4, "#CA8A04"),
    "PEÑALOLEN": (13, 148, 136, "#0D9488"),
    "PEÑALOLÉN": (13, 148, 136, "#0D9488"),
    "PENALOLEN": (13, 148, 136, "#0D9488"),
    "QUILICURA": (192, 38, 211, "#C026D3"),
    "RENCA": (101, 163, 13, "#65A30D"),
    "ESTACION CENTRAL": (225, 29, 72, "#E11D48"),
    "ESTACIÓN CENTRAL": (225, 29, 72, "#E11D48"),
    "INDEPENDENCIA": (2, 132, 199, "#0284C7"),
    "RECOLETA": (217, 119, 6, "#D97706"),
    "MACUL": (124, 58, 237, "#7C3AED"),
    "SAN MIGUEL": (5, 150, 105, "#059669"),
    "QUINTA NORMAL": (185, 28, 28, "#B91C1C"),
    "LA CISTERNA": (29, 78, 216, "#1D4ED8"),
    "EL BOSQUE": (21, 128, 61, "#15803D"),
    "HUECHURABA": (162, 28, 175, "#A21CAF"),
    "LO BARNECHEA": (14, 116, 144, "#0E7490"),
    "CERRO NAVIA": (194, 65, 12, "#C2410C"),
    "LA PINTANA": (109, 40, 217, "#6D28D9"),
    "CONCHALI": (15, 118, 110, "#0F766E"),
    "CONCHALÍ": (15, 118, 110, "#0F766E"),
    "LA REINA": (190, 24, 93, "#BE185D"),
    "VITACURA": (67, 56, 202, "#4338CA"),
    "SAN JOAQUIN": (77, 124, 15, "#4D7C0F"),
    "SAN JOAQUÍN": (77, 124, 15, "#4D7C0F"),
    "PEDRO AGUIRRE CERDA": (157, 23, 77, "#9D174D"),
    "PAC": (157, 23, 77, "#9D174D"),
    "LO PRADO": (3, 105, 161, "#0369A1"),
    "CERRILLOS": (180, 83, 9, "#B45309"),
    "PADRE HURTADO": (6, 95, 70, "#065F46"),
    "SAN RAMON": (134, 25, 143, "#86198F"),
    "SAN RAMÓN": (134, 25, 143, "#86198F"),
    "LA GRANJA": (24, 24, 27, "#52525B"),
    "LO ESPEJO": (239, 68, 68, "#EF4444"),
    "COLINA": (59, 130, 246, "#3B82F6"),
    "LAMPA": (16, 185, 129, "#10B981"),
    "BUIN": (168, 85, 247, "#A855F7"),
    "PAINE": (249, 115, 22, "#F97316"),
    "PEÑAFLOR": (20, 184, 166, "#14B8A6"),
    "PENAFLOR": (20, 184, 166, "#14B8A6"),
    "TALAGANTE": (236, 72, 153, "#EC4899"),
    "MELIPILLA": (99, 102, 241, "#6366F1")
}

LISTA_COLORES_RESPALDO = list(PALETA_COMUNAS_RM.values())

def obtener_color_comuna(comuna_str):
    c_up = str(comuna_str).strip().upper()
    if c_up in PALETA_COMUNAS_RM:
        r, g, b, hex_c = PALETA_COMUNAS_RM[c_up]
        return [r, g, b, 240], hex_c
    idx = int(hashlib.md5(c_up.encode('utf-8')).hexdigest(), 16) % len(LISTA_COLORES_RESPALDO)
    r, g, b, hex_c = LISTA_COLORES_RESPALDO[idx]
    return [r, g, b, 240], hex_c

def obtener_comuna_consistente(identificador):
    comunas = list(COORDENADAS_RM.keys())
    if not identificador:
        return comunas[0]
    hash_val = int(hashlib.md5(str(identificador).encode('utf-8')).hexdigest(), 16)
    return comunas[hash_val % len(comunas)]

def normalizar_rut(val):
    if pd.isna(val) or val is None:
        return ""
    s = str(val).strip().upper().replace(".", "").replace(" ", "")
    if s.endswith(".0"):
        s = s[:-2]
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

# ==============================================================================
# EXPORTADOR EXCEL EJECUTIVO SOBRE FONDO BLANCO
# ==============================================================================
@st.cache_data(show_spinner=False, max_entries=4)
def generar_excel_directorio_blanco(_df_dir, titulo_rep, firma_cache):
    df_dir = _df_dir.copy()
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_dir.to_excel(writer, sheet_name="Directorio_Ejecutivos", index=False, startrow=2)
        ws = writer.sheets["Directorio_Ejecutivos"]

        from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        max_col = len(df_dir.columns)
        max_row = ws.max_row

        title_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
        header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        zebra_even = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
        zebra_odd = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

        fill_verde = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
        fill_morado = PatternFill(start_color="F3E8FF", end_color="F3E8FF", fill_type="solid")
        fill_rojo = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")

        title_font = Font(color="1E3A8A", bold=True, name="Segoe UI", size=13)
        header_font = Font(color="FFFFFF", bold=True, name="Segoe UI", size=10)
        base_font = Font(color="0F172A", bold=False, name="Segoe UI", size=10)
        font_verde = Font(color="15803D", bold=True, name="Segoe UI", size=10)
        font_morado = Font(color="7E22CE", bold=True, name="Segoe UI", size=10)
        font_rojo = Font(color="B91C1C", bold=True, name="Segoe UI", size=10)

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
        top_cell.value = f"📋 {titulo_rep.upper()}"
        top_cell.font = title_font
        top_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        ws.row_dimensions[1].height = 20
        ws.row_dimensions[2].height = 18

        ws.row_dimensions[3].height = 28
        col_names = list(df_dir.columns)
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
            ws.row_dimensions[row_idx].height = 21
            bg_row = zebra_even if (row_idx % 2 == 0) else zebra_odd
            for col_idx in range(1, max_col + 1):
                col_name = col_names[col_idx - 1]
                cell = ws.cell(row=row_idx, column=col_idx)
                val_str = str(cell.value if cell.value is not None else "").strip()
                cell.fill = bg_row
                cell.font = base_font
                cell.border = thin_border
                cell.alignment = Alignment(
                    horizontal="left" if col_name in ["Nombre Completo", "Dirección", "Supervisor"] else "center",
                    vertical="center"
                )
                if col_name == "Estado":
                    if "🟢" in val_str or "ACTIVO" in val_str:
                        cell.fill = fill_verde
                        cell.font = font_verde
                    elif "🟣" in val_str:
                        cell.fill = fill_morado
                        cell.font = font_morado
                    else:
                        cell.fill = fill_rojo
                        cell.font = font_rojo

        for col_idx in range(1, max_col + 1):
            col_letter = get_column_letter(col_idx)
            col_header = str(ws.cell(row=3, column=col_idx).value or "")
            max_len = len(col_header)
            for r_idx in range(4, min(max_row + 1, 200)):
                v = ws.cell(row=r_idx, column=col_idx).value
                if v is not None:
                    max_len = max(max_len, len(str(v)))
            ws.column_dimensions[col_letter].width = max(max_len + 5, 14)

    return output.getvalue()

# ==============================================================================
# CÁLCULO EXACTO DE ANTIGÜEDAD (AÑOS, MESES, DÍAS Y TOTAL DÍAS)
# ==============================================================================
def calcular_antiguedad_exacta(fecha_ing_val, fecha_ref_str=None):
    if pd.isna(fecha_ing_val) or fecha_ing_val is None:
        return "No Registrada"
    s_val = str(fecha_ing_val).strip()
    if not s_val or s_val.upper() in ["NO REGISTRADA", "NAN", "NAT", "NONE"]:
        return "No Registrada"

    dt_ing = None
    if isinstance(fecha_ing_val, (datetime, pd.Timestamp, date)):
        dt_ing = pd.to_datetime(fecha_ing_val, errors='coerce')
    else:
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                dt_ing = datetime.strptime(s_val[:10], fmt)
                break
            except Exception:
                continue
        if dt_ing is None:
            dt_ing = pd.to_datetime(s_val, errors='coerce')

    if pd.isna(dt_ing) or dt_ing is None:
        return "No Registrada"

    d_ini = dt_ing.date() if isinstance(dt_ing, (datetime, pd.Timestamp)) else dt_ing
    try:
        d_fin = datetime.strptime(str(fecha_ref_str)[:10], "%Y-%m-%d").date() if fecha_ref_str else date.today()
    except Exception:
        d_fin = date.today()

    if d_ini > d_fin:
        return "0 días (Ingreso futuro)"

    anios = d_fin.year - d_ini.year
    meses = d_fin.month - d_ini.month
    dias = d_fin.day - d_ini.day

    if dias < 0:
        meses -= 1
        mes_prev = d_fin.month - 1 if d_fin.month > 1 else 12
        anio_prev = d_fin.year if d_fin.month > 1 else d_fin.year - 1
        dias_mes_prev = calendar.monthrange(anio_prev, mes_prev)[1]
        dias += dias_mes_prev

    if meses < 0:
        anios -= 1
        meses += 12

    partes = []
    if anios > 0:
        partes.append(f"{anios} {'año' if anios == 1 else 'años'}")
    if meses > 0:
        partes.append(f"{meses} {'mes' if meses == 1 else 'meses'}")
    if dias > 0 or not partes:
        partes.append(f"{dias} {'día' if dias == 1 else 'días'}")

    dias_totales = (d_fin - d_ini).days
    return f"{', '.join(partes)} ({dias_totales} días)"

# ==============================================================================
# MOTOR DE EXTRACCIÓN MAESTRO DIRECTO (V8 - CRUCE TOTAL DE LICENCIAS Y VACACIONES)
# ==============================================================================
@st.cache_data(show_spinner=False, max_entries=3)
def extraer_bbdd_maestra_mapa_v8(_hojas_semanales, fecha_activa_str, version_datos):
    hojas_semanales = _hojas_semanales

    map_dir_global = {}
    map_dist_global = {}
    map_fec_global = {}
    map_excepciones_global = {}
    hojas_candidatas = []

    for s, df_s in hojas_semanales.items():
        if not isinstance(df_s, pd.DataFrame) or df_s.empty:
            continue
        s_up = str(s).upper().strip()

        if "PROGRAMACI" in s_up and len(df_s) > 1:
            for _, row_p in df_s.iloc[1:].iterrows():
                r_p = normalizar_rut(row_p.iloc[0])
                if r_p and len(r_p) > 5:
                    fila_txt = " ".join([str(v).upper() for v in row_p.values if pd.notna(v)])
                    if "LICENCIA ACHS" in fila_txt:
                        map_excepciones_global[r_p] = "LICENCIA ACHS"
                    elif "LICENCIA MEDICA" in fila_txt or " LM " in f" {fila_txt} ":
                        map_excepciones_global[r_p] = "LICENCIA MEDICA"
                    elif "VACACIONES" in fila_txt:
                        map_excepciones_global[r_p] = "VACACIONES"

        if s_up in ["BDD", "BBDD", "CLIENTE FINAL", "MAESTRO", "BASE DATOS"] or any(kw in s_up for kw in ["BBDD", "BDD", "CLIENTE FINAL", "MAESTRO"]):
            hojas_candidatas.append(s)
            c_r_tmp = detectar_col(df_s.columns, ["rut"], df_s.columns[0])
            c_dir_tmp = detectar_col(df_s.columns, ["dirección", "direccion", "domicilio"], None)
            c_dis_tmp = detectar_col(df_s.columns, ["distrito", "comuna"], None)
            c_fec_tmp = detectar_col(df_s.columns, ["fecha de ingreso", "fechaingreso", "fecha ingreso", "ingreso"], None)

            ruts_s = df_s[c_r_tmp].apply(normalizar_rut)
            if c_dir_tmp and c_dir_tmp in df_s.columns:
                for r_val, d_val in zip(ruts_s, df_s[c_dir_tmp]):
                    if r_val and pd.notna(d_val) and str(d_val).strip() not in ["", "nan", "None"]:
                        map_dir_global[r_val] = str(d_val).strip().upper()
            if c_dis_tmp and c_dis_tmp in df_s.columns:
                for r_val, dis_val in zip(ruts_s, df_s[c_dis_tmp]):
                    if r_val and pd.notna(dis_val) and str(dis_val).strip() not in ["", "nan", "None"]:
                        map_dist_global[r_val] = str(dis_val).strip().upper()
            if c_fec_tmp and c_fec_tmp in df_s.columns:
                for r_val, f_val in zip(ruts_s, df_s[c_fec_tmp]):
                    if r_val and pd.notna(f_val) and str(f_val).strip() not in ["", "nan", "None"]:
                        map_fec_global[r_val] = f_val

            cols_estado_s = [c for c in df_s.columns if any(k in str(c).upper() for k in ["ESTADO", "MOTIVO", "LICENCIA", "VACACION", "OBSERVACION"])]
            for idx_r, row_s in df_s.iterrows():
                r_val = normalizar_rut(row_s.get(c_r_tmp))
                if not r_val or len(r_val) <= 5:
                    continue
                for col_e in cols_estado_s:
                    val_e = str(row_s.get(col_e, "")).strip().upper()
                    col_up = str(col_e).upper()
                    if not val_e or val_e in ["NAN", "NONE", ""]:
                        continue
                    if "LICENCIA ACHS" in val_e or "MUTUAL" in val_e:
                        map_excepciones_global[r_val] = "LICENCIA ACHS"
                    elif "LICENCIA MEDICA" in val_e or val_e == "LM" or ("LICENCIA" in col_up and val_e == "VIGENTE"):
                        map_excepciones_global[r_val] = "LICENCIA MEDICA"
                    elif "VACACION" in val_e or ("VACACION" in col_up and val_e == "VIGENTE"):
                        map_excepciones_global[r_val] = "VACACIONES"

    hoja_bdd = None
    if "BDD" in hojas_semanales:
        hoja_bdd = "BDD"
    elif hojas_candidatas:
        hoja_bdd = max(hojas_candidatas, key=lambda k: len(hojas_semanales[k]))

    if not hoja_bdd:
        return pd.DataFrame()

    df_m = hojas_semanales[hoja_bdd].copy()

    c_rut = detectar_col(df_m.columns, ["rut"], df_m.columns[0])
    c_nom = detectar_col(df_m.columns, ["nombre eac", "nombres", "nombre", "ejecutivo"], None)
    c_ape_p = detectar_col(df_m.columns, ["apellidopaterno", "apellido paterno"], None)
    c_ape_m = detectar_col(df_m.columns, ["apellidomaterno", "apellido materno"], None)
    c_plat = detectar_col(df_m.columns, ["plataforma", "servicio", "canal"], None)
    c_sup = detectar_col(df_m.columns, ["nombre supervisor", "supervisor"], None)
    c_est = detectar_col(df_m.columns, ["estado bbd", "estado bbdd", "estado para turnos", "estado"], None)
    c_mot = detectar_col(df_m.columns, ["motivo inactividad", "motivo", "observaciones"], None)
    c_fec = detectar_col(df_m.columns, ["fecha de ingreso", "fechaingreso", "fecha ingreso", "ingreso"], None)
    c_vac = detectar_col(df_m.columns, ["saldo de vacaciones", "vacaciones"], None)
    c_comuna = detectar_col(df_m.columns, ["distrito", "comuna"], None)
    c_dir = detectar_col(df_m.columns, ["dirección", "direccion", "domicilio"], None)

    df_m['RUT_NORM'] = df_m[c_rut].apply(normalizar_rut)
    df_m = df_m[df_m['RUT_NORM'].str.len() > 5].copy()

    if c_nom and c_nom in df_m.columns:
        if "nombre eac" in str(c_nom).lower() or not c_ape_p:
            df_m['Nombre_Consolidado'] = df_m[c_nom].fillna("SIN NOMBRE").astype(str).str.strip().str.upper()
        else:
            nom_s = df_m[c_nom].fillna("").astype(str).str.strip()
            ap_p = df_m[c_ape_p].fillna("").astype(str).str.strip() if c_ape_p else ""
            ap_m = df_m[c_ape_m].fillna("").astype(str).str.strip() if c_ape_m else ""
            df_m['Nombre_Consolidado'] = (nom_s + " " + ap_p + " " + ap_m).str.replace(r'\s+', ' ', regex=True).str.strip().str.upper()
    else:
        df_m['Nombre_Consolidado'] = df_m['RUT_NORM']

    df_m['Area_Limpia'] = df_m[c_plat].fillna("FRONT").astype(str).str.strip().str.upper() if c_plat and c_plat in df_m.columns else "FRONT"
    df_m['Supervisor_Limpio'] = df_m[c_sup].fillna("SIN ASIGNAR").astype(str).str.strip().str.upper() if c_sup and c_sup in df_m.columns else "SIN ASIGNAR"

    if c_fec and c_fec in df_m.columns:
        fechas_raw = df_m[c_fec].combine_first(df_m['RUT_NORM'].map(map_fec_global))
    else:
        fechas_raw = df_m['RUT_NORM'].map(map_fec_global)

    df_m['Fecha Ingreso Real'] = pd.to_datetime(fechas_raw, errors='coerce').dt.strftime('%d-%m-%Y').fillna("No Registrada")
    df_m['Antigüedad Exacta'] = [calcular_antiguedad_exacta(val, fecha_activa_str) for val in fechas_raw]

    if c_comuna and c_comuna in df_m.columns:
        df_m['Comuna / Domicilio RM'] = df_m[c_comuna].fillna(df_m['RUT_NORM'].map(map_dist_global)).fillna("SANTIAGO").astype(str).str.strip().str.upper()
    else:
        df_m['Comuna / Domicilio RM'] = df_m['RUT_NORM'].map(map_dist_global).fillna(df_m['RUT_NORM'].apply(obtener_comuna_consistente))

    if c_dir and c_dir in df_m.columns:
        df_m['Dirección'] = df_m[c_dir].fillna(df_m['RUT_NORM'].map(map_dir_global)).fillna("Sin Dirección Registrada").astype(str).str.strip().str.upper()
    else:
        df_m['Dirección'] = df_m['RUT_NORM'].map(map_dir_global).fillna("Sin Dirección Registrada")

    est_base = df_m[c_est].fillna("ACTIVO").astype(str).str.strip().str.upper() if c_est and c_est in df_m.columns else pd.Series("ACTIVO", index=df_m.index)
    mot_base = df_m[c_mot].fillna("").astype(str).str.strip().str.upper() if c_mot and c_mot in df_m.columns else pd.Series("", index=df_m.index)

    estados_combinados = []
    for r_norm, e_val, m_val in zip(df_m['RUT_NORM'], est_base, mot_base):
        if r_norm in map_excepciones_global and e_val != "BAJA":
            estados_combinados.append(map_excepciones_global[r_norm])
        elif e_val == "INACTIVO" and any(k in m_val for k in ["LICENCIA", "VACACION", "PERMISO", "MATERNAL", "MUTUAL", "ACHS"]):
            estados_combinados.append(m_val)
        else:
            estados_combinados.append(e_val)
    df_m['Estado Maestro'] = estados_combinados

    df_m['Saldo Vacaciones'] = df_m[c_vac].fillna(0).astype(str).str.strip() if c_vac and c_vac in df_m.columns else "0"

    dict_turnos = {}
    for nombre_hoja, df_hoja in hojas_semanales.items():
        if not dict_turnos and not any(k in str(nombre_hoja).upper() for k in ["BDD", "MAESTRO", "CLIENTE FINAL"]):
            c_ent, c_sal = None, None

            for i, col in enumerate(df_hoja.columns):
                if parsear_fecha_flexible(col) == fecha_activa_str:
                    c_ent = df_hoja.columns[i]
                    c_sal = df_hoja.columns[i+1] if i+1 < len(df_hoja.columns) else None
                    break

            if not c_ent and not df_hoja.empty:
                for i, val in enumerate(df_hoja.iloc[0]):
                    if parsear_fecha_flexible(val) == fecha_activa_str:
                        c_ent = df_hoja.columns[i]
                        c_sal = df_hoja.columns[i+1] if i+1 < len(df_hoja.columns) else None
                        break

            if c_ent and c_sal:
                c_rut_t = detectar_col(df_hoja.columns, ["rut"], df_hoja.columns[0])
                start_row = 1 if "RUT" in str(df_hoja.iloc[0].values).upper() else 0
                for _, r in df_hoja.iloc[start_row:].iterrows():
                    r_n = normalizar_rut(r.get(c_rut_t))
                    if r_n:
                        hi = str(r.get(c_ent))[:5] if pd.notna(r.get(c_ent)) else "--:--"
                        ht = str(r.get(c_sal))[:5] if pd.notna(r.get(c_sal)) else "--:--"
                        if hi != "--:--" or ht != "--:--":
                            dict_turnos[r_n] = f"{hi} - {ht}"

    if not dict_turnos and "BASE CARGA" in hojas_semanales:
        df_bc = hojas_semanales["BASE CARGA"]
        c_fec_bc = detectar_col(df_bc.columns, ["fecha"], "FECHA")
        if c_fec_bc:
            df_bc_dia = df_bc[pd.to_datetime(df_bc[c_fec_bc], errors='coerce').dt.strftime('%Y-%m-%d') == fecha_activa_str]
            c_r = detectar_col(df_bc.columns, ["rut"], df_bc.columns[0])
            c_i = detectar_col(df_bc.columns, ["hora_ini", "entrada"], None)
            c_t = detectar_col(df_bc.columns, ["hora_ter", "salida"], None)
            if c_i and c_t:
                for _, r in df_bc_dia.iterrows():
                    r_n = normalizar_rut(r.get(c_r))
                    if r_n:
                        hi = str(r.get(c_i))[:5] if pd.notna(r.get(c_i)) else "--:--"
                        ht = str(r.get(c_t))[:5] if pd.notna(r.get(c_t)) else "--:--"
                        dict_turnos[r_n] = f"{hi} - {ht}"

    df_m['Turno del Día'] = df_m['RUT_NORM'].map(dict_turnos).fillna("Libre / Sin Turno")

    def clasificar_categoria_estado(val):
        s = str(val).upper()
        if any(k in s for k in ['VACACION', 'LICENCIA', 'PERMISO', 'MATERNAL', 'MUTUAL', 'ACHS', 'LM']):
            return "EXCEPCIONES / LICENCIAS", 2, f"🟣 {s}"
        if 'ACTIV' in s and 'INACTIV' not in s:
            return "ACTIVO", 1, f"🟢 {s}"
        return "INACTIVOS / BAJAS", 3, f"🔴 {s}"

    clasificacion = df_m['Estado Maestro'].apply(clasificar_categoria_estado)
    df_m['Categoria_Estado'] = [x[0] for x in clasificacion]
    df_m['Orden_Estado'] = [x[1] for x in clasificacion]
    df_m['Estado Visual'] = [x[2] for x in clasificacion]
    df_m['Orden_Turno'] = df_m['Turno del Día'].apply(lambda x: 0 if x != "Libre / Sin Turno" and "LIBRE" not in str(x).upper() else 1)

    df_m = df_m.drop_duplicates(subset=['RUT_NORM']).copy()
    df_m.sort_values(by=['Orden_Estado', 'Orden_Turno', 'Nombre_Consolidado'], ascending=[True, True, True], inplace=True)

    df_final = df_m[[
        'RUT_NORM', 'Nombre_Consolidado', 'Area_Limpia', 'Supervisor_Limpio',
        'Fecha Ingreso Real', 'Antigüedad Exacta', 'Turno del Día', 'Estado Visual',
        'Comuna / Domicilio RM', 'Dirección', 'Saldo Vacaciones', 'Categoria_Estado'
    ]].copy()

    df_final.columns = [
        'RUT', 'Nombre Completo', 'Área', 'Supervisor',
        'Fecha Ingreso', 'Antigüedad', 'Turno del Día', 'Estado',
        'Comuna / Domicilio RM', 'Dirección', 'Días Vacaciones', 'Categoria_Estado'
    ]

    return df_final

# ==============================================================================
# RENDERIZADO DEL MÓDULO
# ==============================================================================
def renderizar_modulo_base_ejecutivos(con_global, fecha_activa_str):
    st.markdown("""
    <style>
        .card-exec-header {
            background: linear-gradient(135deg, rgba(15, 23, 42, 0.95) 0%, rgba(30, 41, 59, 0.9) 100%);
            border: 1px solid rgba(56, 189, 248, 0.4);
            border-left: 6px solid #38BDF8;
            border-radius: 16px;
            padding: 22px 28px;
            margin-bottom: 22px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
        }
        .exec-kpi-container { display: flex; gap: 15px; margin-bottom: 20px; }
        .exec-kpi-box {
            background: linear-gradient(145deg, #131D31 0%, #1E293B 100%);
            border: 2px solid #334155; border-radius: 16px;
            padding: 18px 14px; flex: 1; text-align: center; box-shadow: 0 8px 20px rgba(0,0,0,0.35);
            min-height: 112px; display: flex; flex-direction: column; justify-content: center;
        }
        .exec-kpi-title { font-size: 0.84rem; color: #CBD5E1; text-transform: uppercase; font-weight: 800; letter-spacing: 0.6px; margin-bottom: 6px; }
        .exec-kpi-value { font-size: 2.3rem; font-weight: 900; color: #F8FAFC; line-height: 1.1; }
        .comuna-legend-grid {
            display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; margin-bottom: 8px;
            background: rgba(15, 23, 42, 0.75); border: 1px solid #334155; border-radius: 12px; padding: 12px 14px;
        }
        .comuna-chip {
            display: inline-flex; align-items: center; gap: 6px;
            background: #1E293B; border: 1px solid #475569; border-radius: 8px;
            padding: 4px 10px; font-size: 0.78rem; font-weight: 700; color: #F8FAFC;
        }
        .comuna-dot { width: 11px; height: 11px; border-radius: 50%; display: inline-block; border: 1px solid #FFFFFF; }
        [data-testid="stDataFrame"] table thead tr th {
            background-color: #1E3A8A !important;
            color: #F8FAFC !important;
            font-weight: bold !important;
            text-transform: uppercase !important;
        }
    </style>
    <div class="card-exec-header">
        <h2 style="color: #FFFFFF; margin: 0; font-size: 2rem; font-weight: 900;">📋 Base de Datos Maestra de Ejecutivos</h2>
        <p style="color: #94A3B8; margin: 6px 0 0 0; font-size: 1.05rem;">
            Directorio Universal, Control de Licencias/Vacaciones, Antigüedad Exacta y Geolocalización RM por Comuna
        </p>
    </div>
    """, unsafe_allow_html=True)

    hojas_semanales = st.session_state.get("excel_colaciones_hojas", {})
    if not hojas_semanales:
        st.warning("⚠️ No hay archivos en memoria. Asegúrate de tener cargada la Malla BDD en 'Ingesta de Datos'.")
        return

    version_datos = st.session_state.get("version_datos", 1)
    df_maestro = extraer_bbdd_maestra_mapa_v8(hojas_semanales, fecha_activa_str, version_datos)

    if df_maestro.empty:
        st.warning("⚠️ No se encontró la pestaña 'BBDD' o 'Cliente Final' en el archivo Excel subido.")
        return

    # ==============================================================================
    # BARRA DE FILTROS ORGANIZADA
    # ==============================================================================
    c_f1, c_f2, c_f3, c_f4, c_f5 = st.columns([1.3, 1.8, 1.4, 1.7, 1.1])
    
    areas_disp = ["TODOS"] + sorted(list(set(df_maestro['Área'].dropna().astype(str).unique())))
    sel_area = c_f1.selectbox("🏢 Área / Servicio:", areas_disp)
    
    opciones_estado = [
        "DOTACIÓN VIGENTE (Activos + Licencias)",
        "SOLO ACTIVOS",
        "SOLO LICENCIAS / VACACIONES",
        "INACTIVOS / BAJAS",
        "TODOS (Incluye Bajas)"
    ]
    sel_estado = c_f2.selectbox("📌 Estado Operativo:", opciones_estado, index=0)

    comunas_disp = ["TODAS"] + sorted(list(set(df_maestro['Comuna / Domicilio RM'].dropna().astype(str).unique())))
    sel_comuna = c_f3.selectbox("📍 Comuna / Distrito:", comunas_disp)
    
    q_busqueda = c_f4.text_input("🔍 Buscar por RUT o Nombre:", placeholder="Ej. 12.345.678-9 o Juan")
    
    with c_f5:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        mostrar_mapa = st.checkbox("🗺️ Ver Mapa RM", value=True)

    df_flt = df_maestro.copy()
    
    if sel_area != "TODOS":
        df_flt = df_flt[df_flt['Área'] == sel_area]

    if sel_estado == "DOTACIÓN VIGENTE (Activos + Licencias)":
        df_flt = df_flt[df_flt['Categoria_Estado'].isin(["ACTIVO", "EXCEPCIONES / LICENCIAS"])]
    elif sel_estado == "SOLO ACTIVOS":
        df_flt = df_flt[df_flt['Categoria_Estado'] == "ACTIVO"]
    elif sel_estado == "SOLO LICENCIAS / VACACIONES":
        df_flt = df_flt[df_flt['Categoria_Estado'] == "EXCEPCIONES / LICENCIAS"]
    elif sel_estado == "INACTIVOS / BAJAS":
        df_flt = df_flt[df_flt['Categoria_Estado'] == "INACTIVOS / BAJAS"]

    if sel_comuna != "TODAS":
        df_flt = df_flt[df_flt['Comuna / Domicilio RM'] == sel_comuna]

    if q_busqueda.strip():
        txt = q_busqueda.strip().upper()
        df_flt = df_flt[
            df_flt['RUT'].astype(str).str.upper().str.contains(txt) | 
            df_flt['Nombre Completo'].astype(str).str.upper().str.contains(txt)
        ]

    tot_act = len(df_flt[df_flt['Categoria_Estado'] == 'ACTIVO'])
    tot_exc = len(df_flt[df_flt['Categoria_Estado'] == 'EXCEPCIONES / LICENCIAS'])
    tot_inact = len(df_flt[df_flt['Categoria_Estado'] == 'INACTIVOS / BAJAS'])

    st.markdown(f"""
    <div class="exec-kpi-container">
        <div class="exec-kpi-box" style="border-color:#0284C7;"><div class="exec-kpi-title">👥 Dotación en Vista (Total BBDD: {len(df_maestro)})</div><div class="exec-kpi-value" style="color:#38BDF8;">{len(df_flt)}</div></div>
        <div class="exec-kpi-box" style="border-color:#059669;"><div class="exec-kpi-title">🟢 Activos Operativos</div><div class="exec-kpi-value" style="color:#10B981;">{tot_act}</div></div>
        <div class="exec-kpi-box" style="border-color:#9333EA;"><div class="exec-kpi-title">🟣 Excepciones / Licencias / Vac.</div><div class="exec-kpi-value" style="color:#C084FC;">{tot_exc}</div></div>
        <div class="exec-kpi-box" style="border-color:#DC2626;"><div class="exec-kpi-title">🔴 Inactivos / Bajas</div><div class="exec-kpi-value" style="color:#EF4444;">{tot_inact}</div></div>
    </div>
    """, unsafe_allow_html=True)

    df_tabla = df_flt.drop(columns=['Categoria_Estado'])

    c_tit_dir, c_btn_dir = st.columns([2.4, 1.1])
    c_tit_dir.markdown("#### 📑 Nómina Maestra Filtrada")
    excel_dir_bytes = generar_excel_directorio_blanco(
        df_tabla,
        f"Directorio Maestro de Ejecutivos ({sel_area} - {sel_comuna}) - {fecha_activa_str}",
        f"dir_{fecha_activa_str}_{sel_area}_{sel_estado}_{sel_comuna}_{len(df_tabla)}"
    )
    c_btn_dir.download_button(
        label="📥 Exportar Directorio Visual (Excel)",
        data=excel_dir_bytes,
        file_name=f"Directorio_Ejecutivos_WFM_{fecha_activa_str}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch"
    )

    st.dataframe(df_tabla, width="stretch", hide_index=True, height=390)

    # ==============================================================================
    # MAPA INTERACTIVO COMPATIBLE CON PLOTLY 6+ (SCATTERMAP) Y HOVER NOMBRE + DIRECCIÓN
    # ==============================================================================
    if mostrar_mapa:
        st.markdown("<br>", unsafe_allow_html=True)
        subtitulo_mapa = f"Comuna: {sel_comuna}" if sel_comuna != "TODAS" else "Región Metropolitana"

        c_m_tit, c_m_fondo = st.columns([2.3, 1.1])
        c_m_tit.markdown(f"### 🗺️ Radar Territorial por Comunas ({subtitulo_mapa} — {len(df_flt)} ejecutivos)")
        c_m_tit.caption("💡 Pasa el mouse sobre cualquier punto del mapa para ver el **Nombre del Ejecutivo**, **Comuna**, **Dirección donde vive**, **Turno** y **Estado**.")

        estilo_fondo_sel = c_m_fondo.radio(
            "🎨 Color de Fondo del Mapa:",
            ["⚪ Blanco (Calles Nítidas)", "⚫ Negro (Radar Oscuro)"],
            index=0,
            horizontal=True
        )
        
        df_mapa = df_flt.copy()
        df_mapa['lat'] = df_mapa['Comuna / Domicilio RM'].map(lambda x: COORDENADAS_RM.get(str(x).upper().strip(), (None, None))[0])
        df_mapa['lon'] = df_mapa['Comuna / Domicilio RM'].map(lambda x: COORDENADAS_RM.get(str(x).upper().strip(), (None, None))[1])
        df_mapa = df_mapa.dropna(subset=['lat', 'lon']).copy()

        if not df_mapa.empty:
            np.random.seed(42)
            dispersion = 0.0042 if sel_comuna != "TODAS" else 0.0078
            df_mapa['lat'] = df_mapa['lat'] + np.random.normal(0, dispersion, size=len(df_mapa))
            df_mapa['lon'] = df_mapa['lon'] + np.random.normal(0, dispersion, size=len(df_mapa))
            
            colores_comuna_info = [obtener_color_comuna(c) for c in df_mapa['Comuna / Domicilio RM']]
            df_mapa['color_hex'] = [x[1] for x in colores_comuna_info]

            if sel_comuna != "TODAS" and sel_comuna.upper().strip() in COORDENADAS_RM:
                lat_centro, lon_centro = COORDENADAS_RM[sel_comuna.upper().strip()]
                zoom_mapa = 12.2
            else:
                lat_centro, lon_centro = -33.4650, -70.6500
                zoom_mapa = 9.8

            es_blanco = "Blanco" in estilo_fondo_sel
            map_style_str = "open-street-map" if es_blanco else "carto-darkmatter"
            borde_contorno = "#0F172A" if es_blanco else "#FFFFFF"

            fig_mapa = go.Figure()

            custom_data_arr = np.stack((
                df_mapa['Nombre Completo'].astype(str),
                df_mapa['Comuna / Domicilio RM'].astype(str),
                df_mapa['Dirección'].astype(str),
                df_mapa['Estado'].astype(str),
                df_mapa['Área'].astype(str),
                df_mapa['Turno del Día'].astype(str),
                df_mapa['RUT'].astype(str)
            ), axis=-1)

            hover_tmpl = (
                "<b>👤 %{customdata[0]}</b> (RUT: %{customdata[6]})<br>"
                "📍 <b>Vive en Comuna:</b> %{customdata[1]}<br>"
                "🏠 <b>Dirección:</b> %{customdata[2]}<br>"
                "📌 <b>Estado:</b> %{customdata[3]} | 🏢 <b>Área:</b> %{customdata[4]}<br>"
                "⏰ <b>Turno Hoy:</b> %{customdata[5]}"
                "<extra></extra>"
            )

            # Compatibilidad universal entre Plotly 6+ (Scattermap) y versiones previas (Scattermapbox)
            if hasattr(go, "Scattermap"):
                fig_mapa.add_trace(go.Scattermap(
                    lat=df_mapa['lat'],
                    lon=df_mapa['lon'],
                    mode='markers',
                    marker=dict(size=17, color=borde_contorno, opacity=0.95),
                    hoverinfo='skip',
                    showlegend=False
                ))
                fig_mapa.add_trace(go.Scattermap(
                    lat=df_mapa['lat'],
                    lon=df_mapa['lon'],
                    mode='markers',
                    marker=dict(size=13, color=df_mapa['color_hex'], opacity=0.95),
                    customdata=custom_data_arr,
                    hovertemplate=hover_tmpl,
                    showlegend=False
                ))
                fig_mapa.update_layout(
                    map=dict(
                        style=map_style_str,
                        center=dict(lat=lat_centro, lon=lon_centro),
                        zoom=zoom_mapa
                    ),
                    margin=dict(l=0, r=0, t=0, b=0),
                    height=560,
                    paper_bgcolor="#0F172A",
                    hoverlabel=dict(
                        bgcolor="#0F172A",
                        bordercolor="#38BDF8",
                        font=dict(color="#F8FAFC", size=13, family="Segoe UI, sans-serif")
                    )
                )
            else:
                fig_mapa.add_trace(go.Scattermapbox(
                    lat=df_mapa['lat'],
                    lon=df_mapa['lon'],
                    mode='markers',
                    marker=dict(size=17, color=borde_contorno, opacity=0.95),
                    hoverinfo='skip',
                    showlegend=False
                ))
                fig_mapa.add_trace(go.Scattermapbox(
                    lat=df_mapa['lat'],
                    lon=df_mapa['lon'],
                    mode='markers',
                    marker=dict(size=13, color=df_mapa['color_hex'], opacity=0.95),
                    customdata=custom_data_arr,
                    hovertemplate=hover_tmpl,
                    showlegend=False
                ))
                fig_mapa.update_layout(
                    mapbox=dict(
                        style=map_style_str,
                        center=dict(lat=lat_centro, lon=lon_centro),
                        zoom=zoom_mapa
                    ),
                    margin=dict(l=0, r=0, t=0, b=0),
                    height=560,
                    paper_bgcolor="#0F172A",
                    hoverlabel=dict(
                        bgcolor="#0F172A",
                        bordercolor="#38BDF8",
                        font=dict(color="#F8FAFC", size=13, family="Segoe UI, sans-serif")
                    )
                )

            st.plotly_chart(fig_mapa, width="stretch", config={"scrollZoom": True, "displayModeBar": True})

            # Leyenda visual de colores por Comuna con conteo de ejecutivos
            resumen_comunas = (
                df_mapa.groupby(['Comuna / Domicilio RM', 'color_hex'])
                .size()
                .reset_index(name='cant')
                .sort_values(by='cant', ascending=False)
            )
            chips_html = "".join([
                f"<div class='comuna-chip'><span class='comuna-dot' style='background-color:{r['color_hex']};'></span>"
                f"{r['Comuna / Domicilio RM']} <span style='color:#38BDF8;'>({r['cant']})</span></div>"
                for _, r in resumen_comunas.iterrows()
            ])
            st.markdown(
                f"<div style='font-size:0.85rem; color:#94A3B8; font-weight:700; margin-top:8px;'>🎨 Código de Colores por Comuna (Cada comuna tiene su propio color identificador):</div>"
                f"<div class='comuna-legend-grid'>{chips_html}</div>",
                unsafe_allow_html=True
            )
        else:
            st.info("ℹ️ No hay coordenadas válidas para dibujar el mapa con los filtros seleccionados.")