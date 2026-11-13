import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import duckdb
import io
import re
from datetime import datetime, timedelta, time
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

try:
    import plotly.graph_objects as go
    HAY_PLOTLY = True
except ImportError:
    HAY_PLOTLY = False

# ==============================================================================
# ESTILOS CSS CONSOLA MODERNA WFM
# ==============================================================================
def inyectar_estilos_intervalos():
    st.markdown("""
    <style>
        .kpi-container { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
        .kpi-box { background: linear-gradient(145deg, #131D2E 0%, #1C273C 100%); border: 1px solid #2A3952; border-radius: 8px; padding: 12px 10px; flex: 1; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3); display: flex; flex-direction: column; justify-content: center; }
        .kpi-title { font-size: 0.65rem; color: #94A3B8; text-transform: uppercase; font-weight: 800; margin-bottom: 4px; letter-spacing: 0.5px; }
        .kpi-value { font-size: 1.5rem; font-weight: 900; color: #F8FAFC; }
        .kpi-sub { font-size: 0.72rem; color: #94A3B8; font-weight: 600; margin-top: 2px; }
        .text-green { color: #2CA02C !important; }
        .text-red { color: #F87171 !important; }
        .text-yellow { color: #FBBF24 !important; }
        .text-blue { color: #1F77B4 !important; }
        .text-orange { color: #FF7F0E !important; }
        
        .html-matriz table { width: 100%; border-collapse: collapse; font-size: 13px; text-align: center; color: #E2E8F0; margin-top: 15px; }
        .html-matriz th, .html-matriz td { border: 1px solid #2D3748; padding: 8px 4px; }
        .html-matriz thead th { font-weight: 800; border: 1px solid #1A202C; }
        .html-matriz thead th:nth-child(1) { background-color: #1F497D !important; color: white !important; }
        .html-matriz thead th:nth-child(2), .html-matriz thead th:nth-child(3), .html-matriz thead th:nth-child(4), .html-matriz thead th:nth-child(5) { background-color: #203764 !important; color: white !important; }
        .html-matriz thead th:nth-child(6), .html-matriz thead th:nth-child(7) { background-color: #FFFF00 !important; color: black !important; }
        .html-matriz thead th:nth-child(8) { background-color: #1F497D !important; color: white !important; }
        .html-matriz tbody tr:nth-child(even) { background-color: #1E293B; }
        .html-matriz tbody tr:nth-child(odd) { background-color: #0F172A; }
    </style>
    """, unsafe_allow_html=True)

# ==============================================================================
# FUNCIONES DE CARGA Y EXCEL
# ==============================================================================
@st.cache_data(show_spinner=False, max_entries=4)
def obtener_metas_intervalo_30m(_hojas_dict, dia_nombre="LUNES", version_datos=1):
    hojas_dict = _hojas_dict
    fc_llamadas_def = {f"{h:02d}:{m:02d}": 0 for h in range(7, 24) for m in (0, 30)}
    fc_dotacion_def = {k: 0 for k in fc_llamadas_def.keys()}

    if "Cuadro de Mando" in hojas_dict:
        df_cm = hojas_dict["Cuadro de Mando"]
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
                    
            df_data = df_cm.iloc[header_idx+1:].copy()
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
                                    fc_llamadas_def[h_str] = max(0, int(fc_val) - prev_fc_acum)
                                    prev_fc_acum = int(fc_val)
                            
                            dot_col = next((c for c in df_data.columns if "DOTACION FC" in c), None)
                            if dot_col:
                                dot_val = pd.to_numeric(r[dot_col], errors="coerce")
                                if pd.notna(dot_val):
                                    fc_dotacion_def[h_str] = int(dot_val)
                    except:
                        pass
    return fc_llamadas_def, fc_dotacion_def

def sincronizar_todo_el_dia(con, hojas_dict, fecha_activa_str, intervalos_30m):
    if "Cuadro de Mando" not in hojas_dict:
        return 0
    df_cm = hojas_dict["Cuadro de Mando"]
    
    header_idx = None
    for idx, row in df_cm.head(30).iterrows():
        row_upper = [str(x).upper().strip() for x in row.values]
        if any("INTERVALO" in x for x in row_upper) and any("10MIN" in x or "10 MIN" in x for x in row_upper):
            header_idx = idx
            
    if header_idx is None:
        return 0
    
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
            
    df_data = df_cm.iloc[header_idx+1:].copy()
    df_data.columns = cols
    
    def safe_int(r, col_names):
        for c in col_names:
            if c in df_data.columns:
                try:
                    v = pd.to_numeric(r[c], errors='coerce')
                    return max(0, int(v)) if pd.notna(v) else 0
                except:
                    pass
        return 0

    def safe_float(r, col_names):
        for c in col_names:
            if c in df_data.columns:
                try:
                    v = pd.to_numeric(r[c], errors='coerce')
                    return max(0.0, float(v)) if pd.notna(v) else 0.0
                except:
                    pass
        return 0.0

    count_inserted = 0
    for _, r in df_data.iterrows():
        int_val = str(r.get("INTERVALO", ""))
        if not int_val or int_val == "nan":
            continue
        
        h_ini = ""
        if "-" in int_val:
            p = int_val.split("-")[0].strip()
            if ":" in p:
                h_ini = f"{int(p.split(':')[0]):02d}:{int(p.split(':')[1]):02d}"
        
        if not h_ini:
            continue
        
        full_interval = next((i for i in intervalos_30m if i.startswith(h_ini)), None)
        if not full_interval:
            continue
        
        entrantes = safe_int(r, ["LLAMADAS INGRESADAS", "LLAMADAS ENTRANTES"])
        atendidas = safe_int(r, ["LLAM. CIERRE INTERVALO", "ATENDIDAS"])
        perdidas = safe_int(r, ["LLAMADAS PERDIDAS", "CAIDAS"])
        m10 = safe_int(r, ["10MIN. FC", "10 MIN."])
        m20 = safe_int(r, ["20MIN. FC", "20 MIN."])
        dotacion = safe_int(r, ["REAL DOTACION", "DOTACION REAL"])
        sl = safe_float(r, ["NIVEL SERVICIO"])
        if 0 < sl <= 1.0:
            sl = sl * 100
        
        if entrantes > 0 or atendidas > 0 or dotacion > 0 or m10 > 0:
            con.execute(f"""
                INSERT OR REPLACE INTO control_intervalos_diario 
                (fecha, intervalo, llamadas_10m, llamadas_20m, llamadas_perdidas, llamadas_entrantes, llamadas_atendidas, dotacion_real, ausencias, sl_real, fc_acum_manual, llamadas_cierre)
                VALUES ('{fecha_activa_str}', '{full_interval}', {m10}, {m20}, {perdidas}, {entrantes}, {atendidas}, {dotacion}, 0, {sl}, 0, 0)
            """)
            count_inserted += 1
    return count_inserted

@st.cache_data(show_spinner=False, max_entries=4)
def generar_excel_matriz_cierre(_df_matriz, firma_cache):
    df_matriz = _df_matriz
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_matriz.to_excel(writer, sheet_name="Cierre_Turno", index=False)
        ws = writer.sheets["Cierre_Turno"]
        
        dark_blue = PatternFill("solid", fgColor="1F497D")
        mid_blue = PatternFill("solid", fgColor="203764")
        yellow = PatternFill("solid", fgColor="FFFF00")
        
        white_font = Font(color="FFFFFF", bold=True)
        black_font = Font(color="000000", bold=True)
        red_font = Font(color="FF0000", bold=True)
        green_font = Font(color="00B050", bold=True)
        
        for col_num in range(1, len(df_matriz.columns) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            if col_num == 1:
                cell.fill = dark_blue
                cell.font = white_font
            elif col_num in [2, 3, 4, 5, 8]:
                cell.fill = mid_blue
                cell.font = white_font
            elif col_num in [6, 7]:
                cell.fill = yellow
                cell.font = black_font

        for row_num in range(2, len(df_matriz) + 2):
            cump_cell = ws.cell(row=row_num, column=7)
            if cump_cell.value is not None:
                cump_cell.font = red_font if cump_cell.value < 0 else green_font
                cump_cell.alignment = Alignment(horizontal="center")
                    
            pct_cell = ws.cell(row=row_num, column=8)
            if pct_cell.value is not None:
                pct_cell.number_format = '0%'
                pct_cell.font = red_font if pct_cell.value < 0 else green_font
                pct_cell.alignment = Alignment(horizontal="center")
            
            for c in range(1, 9):
                ws.cell(row=row_num, column=c).alignment = Alignment(horizontal="center")
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = 16
    return output.getvalue()

# ==============================================================================
# MÓDULO PRINCIPAL: CONTROL DE INTERVALOS
# ==============================================================================
def renderizar_modulo_intervalos(con, fecha_activa_str):
    inyectar_estilos_intervalos()

    es_admin = bool(
        st.session_state.get("es_admin_wfm", False)
        or st.session_state.get("permiso_wfm", "ADMIN") == "ADMIN"
        or str(st.session_state.get("usuario_actual", "GTR")).strip().upper() == "GTR"
    )

    if "schema_intervalos_ok" not in st.session_state:
        con.execute("""
            CREATE TABLE IF NOT EXISTS control_intervalos_diario (
                fecha VARCHAR, intervalo VARCHAR, llamadas_10m INTEGER, llamadas_20m INTEGER,
                llamadas_perdidas INTEGER, llamadas_entrantes INTEGER, llamadas_atendidas INTEGER,
                dotacion_real INTEGER, ausencias INTEGER, sl_real FLOAT, fc_acum_manual INTEGER, llamadas_cierre INTEGER,
                PRIMARY KEY (fecha, intervalo)
            );
        """)
        try:
            con.execute("ALTER TABLE control_intervalos_diario ADD COLUMN sl_real FLOAT;")
        except:
            pass
        try:
            con.execute("ALTER TABLE control_intervalos_diario ADD COLUMN llamadas_cierre INTEGER;")
        except:
            pass
        st.session_state["schema_intervalos_ok"] = True

    intervalos_30m = [f"{h:02d}:{m:02d} - {((h if m == 0 else h + 1) % 24):02d}:{(30 if m == 0 else 0):02d}" for h in range(7, 24) for m in (0, 30)]
    
    hojas_semanales = st.session_state.get("excel_intervalos_hojas", st.session_state.get("excel_colaciones_hojas", {}))
    if "Cuadro de Mando" not in hojas_semanales and "Cuadro de Mando" in st.session_state.get("excel_colaciones_hojas", {}):
        hojas_semanales = st.session_state.get("excel_colaciones_hojas", {})

    version_datos = st.session_state.get("version_datos", 1)
    
    df_check = con.execute(f"SELECT COUNT(*) FROM control_intervalos_diario WHERE fecha = '{fecha_activa_str}'").fetchone()[0]
    if df_check == 0 and "Cuadro de Mando" in hojas_semanales:
        if not st.session_state.get(f"limpiado_manual_int_{fecha_activa_str}", False):
            cant = sincronizar_todo_el_dia(con, hojas_semanales, fecha_activa_str, intervalos_30m)
            if cant > 0:
                st.toast(f"✅ Se auto-completaron {cant} intervalos históricos.", icon="🤖")
                st.rerun()

    if es_admin:
        c_btn1, c_btn2, c_btn3 = st.columns([2.5, 1.5, 1.5])
        with c_btn2:
            if st.button("🔄 Sincronizar Excel", width="stretch"):
                st.session_state[f"limpiado_manual_int_{fecha_activa_str}"] = False
                if "Cuadro de Mando" in hojas_semanales:
                    con.execute(f"DELETE FROM control_intervalos_diario WHERE fecha = '{fecha_activa_str}'")
                    cant = sincronizar_todo_el_dia(con, hojas_semanales, fecha_activa_str, intervalos_30m)
                    st.success(f"✅ Excel sincronizado ({cant} intervalos).")
                    st.rerun()
                else:
                    st.toast("Modo Manual activo.", icon="✍️")
                    
        with c_btn3:
            if st.button("🧹 Limpiar Día", width="stretch"):
                st.session_state[f"limpiado_manual_int_{fecha_activa_str}"] = True
                con.execute(f"DELETE FROM control_intervalos_diario WHERE fecha = '{fecha_activa_str}'")
                st.success("✅ Datos e historial borrados para este día.")
                st.rerun()

    fc_llamadas_map, fc_dot_map = obtener_metas_intervalo_30m(hojas_semanales, "LUNES", version_datos)

    df_todos_int = con.execute(f"SELECT * FROM control_intervalos_diario WHERE fecha = '{fecha_activa_str}' ORDER BY intervalo").df()
    map_guardados_int = {str(row["intervalo"]): row.to_dict() for _, row in df_todos_int.iterrows()} if not df_todos_int.empty else {}

    last_valid_idx = -1
    for i, lbl in enumerate(intervalos_30m):
        if lbl in map_guardados_int:
            rg = map_guardados_int[lbl]
            if int(rg.get("llamadas_entrantes", 0)) > 0 or int(rg.get("llamadas_atendidas", 0)) > 0:
                last_valid_idx = i

    c_sel_int, c_vacio = st.columns([2.6, 1.4])
    if not es_admin and last_valid_idx >= 0:
        idx_def_int = last_valid_idx
    else:
        h_act = datetime.now().hour
        m_act = 30 if datetime.now().minute >= 30 else 0
        tag_act = f"{h_act:02d}:{m_act:02d}"
        idx_def_int = next((i for i, lbl in enumerate(intervalos_30m) if lbl.startswith(tag_act)), 2)

    lbl_selector = "⏱️ Seleccionar Bloque a Gestionar:" if es_admin else "⏱️ Seleccionar Bloque Horario a Consultar:"
    int_seleccionado = c_sel_int.selectbox(lbl_selector, intervalos_30m, index=idx_def_int)
    h_tag = int_seleccionado.split(" - ")[0]
    fc_dot_bloque = fc_dot_map.get(h_tag, 0)

    # ==========================================================================
    # MOTOR DE DISTRIBUCIÓN INTELIGENTE (ANTI-PICOS Y ANTI-CAÍDAS A CERO)
    # ==========================================================================
    n_int = len(intervalos_30m)
    fc_list = [fc_llamadas_map.get(lbl.split(" - ")[0], 0) for lbl in intervalos_30m]

    acum_entr_interp = [0] * n_int
    acum_aten_interp = [0] * n_int
    marg_entr_list = [0] * n_int
    marg_aten_list = [0] * n_int

    if last_valid_idx >= 0:
        anchors = []
        prev_e_val = 0
        prev_a_val = 0
        for i in range(last_valid_idx + 1):
            lbl = intervalos_30m[i]
            if lbl in map_guardados_int:
                rg = map_guardados_int[lbl]
                e_val = int(rg.get("llamadas_entrantes", 0))
                a_val = int(rg.get("llamadas_atendidas", 0))
                if e_val > prev_e_val or a_val > prev_a_val:
                    e_clean = max(prev_e_val, e_val)
                    a_clean = max(prev_a_val, a_val)
                    anchors.append((i, e_clean, a_clean))
                    prev_e_val = e_clean
                    prev_a_val = a_clean

        prev_idx = -1
        prev_e = 0
        prev_a = 0

        for idx_anc, e_anc, a_anc in anchors:
            delta_e = max(0, e_anc - prev_e)
            delta_a = max(0, a_anc - prev_a)

            valid_span = [k for k in range(prev_idx + 1, idx_anc + 1) if (fc_list[k] > 0 and (prev_idx >= 0 or k == idx_anc)) or k == idx_anc]
            if not valid_span:
                valid_span = [idx_anc]

            total_fc_span = sum(fc_list[k] for k in valid_span)
            rem_e = delta_e
            rem_a = delta_a

            for pos, k in enumerate(valid_span):
                if pos == len(valid_span) - 1:
                    alloc_e = rem_e
                    alloc_a = rem_a
                else:
                    weight = (fc_list[k] / total_fc_span) if total_fc_span > 0 else (1.0 / len(valid_span))
                    alloc_e = int(round(delta_e * weight))
                    alloc_a = int(round(delta_a * weight))
                    rem_e -= alloc_e
                    rem_a -= alloc_a
                marg_entr_list[k] = max(0, alloc_e)
                marg_aten_list[k] = max(0, alloc_a)

            prev_idx = idx_anc
            prev_e = e_anc
            prev_a = a_anc

        run_e = 0
        run_a = 0
        for i in range(n_int):
            if i <= last_valid_idx:
                run_e += marg_entr_list[i]
                run_a += marg_aten_list[i]
            acum_entr_interp[i] = run_e
            acum_aten_interp[i] = run_a

    # ==========================================================================
    # VALORES Y CONSOLA DE ENTRADA DE DATOS (EXCLUSIVA PARA ADMIN)
    # ==========================================================================
    idx_sel = intervalos_30m.index(int_seleccionado)
    r_prev = map_guardados_int.get(int_seleccionado)
    esta_guardado_seleccionado = r_prev is not None

    prev_entr_base = acum_entr_interp[idx_sel - 1] if idx_sel > 0 else 0
    prev_aten_base = acum_aten_interp[idx_sel - 1] if idx_sel > 0 else 0

    ultimo_perd, ultimo_sl, ultimo_dot = 0, 0.0, 0
    ultimo_int_guardado_nombre = None
    for past_int in reversed(intervalos_30m[:idx_sel]):
        if past_int in map_guardados_int:
            p_r = map_guardados_int[past_int]
            ultimo_perd = int(p_r.get("llamadas_perdidas", 0))
            ultimo_sl = float(p_r.get("sl_real", 0.0)) if pd.notna(p_r.get("sl_real")) else 0.0
            ultimo_dot = int(p_r.get("dotacion_real", 0))
            ultimo_int_guardado_nombre = past_int
            break

    val_10m = max(0, int(r_prev.get("llamadas_10m", 0))) if r_prev else 0
    val_20m = max(0, int(r_prev.get("llamadas_20m", 0))) if r_prev else 0
    val_entr_acum = max(0, int(r_prev.get("llamadas_entrantes", prev_entr_base))) if r_prev else max(0, prev_entr_base)
    val_aten_acum = max(0, int(r_prev.get("llamadas_atendidas", prev_aten_base))) if r_prev else max(0, prev_aten_base)
    val_perd_acum = max(0, int(r_prev.get("llamadas_perdidas", ultimo_perd))) if r_prev else max(0, ultimo_perd)
    val_dot = max(0, int(r_prev.get("dotacion_real", ultimo_dot))) if r_prev else max(0, ultimo_dot)
    val_sl_real = max(0.0, float(r_prev.get("sl_real", 0.0))) if (r_prev and pd.notna(r_prev.get("sl_real"))) else max(0.0, ultimo_sl)

    st.markdown("---")
    if es_admin:
        with st.expander(f"📝 Consola de Entrada de Datos • Bloque {int_seleccionado}", expanded=True):
            st.info("💡 **Sistema Acumulado Inteligente:** Ingresa los acumulados totales de BrightPattern. El gráfico y la matriz solo se actualizarán al presionar **Guardar Datos**.")
            
            with st.form(key=f"form_intervalo_{int_seleccionado}"):
                c4, c5, c6, c_sl = st.columns(4)
                in_entr = c4.number_input("Entrantes (ACUMULADO Total):", min_value=0, value=val_entr_acum, step=1)
                in_aten = c5.number_input("Atendidas (ACUMULADO Total):", min_value=0, value=val_aten_acum, step=1)
                in_perd = c6.number_input("Perdidas (ACUMULADO Total):", min_value=0, value=val_perd_acum, step=1)
                in_sl_real = c_sl.number_input("Nivel de Servicio (%) BP:", min_value=0.0, max_value=100.0, value=float(val_sl_real), step=0.1)

                st.markdown("<br>", unsafe_allow_html=True)
                c7, c8, c9 = st.columns(3)
                in_dot = c7.number_input("Dotación Real:", min_value=0, value=val_dot, step=1)
                in_10m = c8.number_input("10 Min (Acumulado o Neto):", min_value=0, value=val_10m, step=1)
                in_20m = c9.number_input("20 Min (Acumulado o Neto):", min_value=0, value=val_20m, step=1)

                submit_guardar = st.form_submit_button("💾 Guardar Datos", width="stretch")
                if submit_guardar:
                    con.execute(f"""
                        INSERT OR REPLACE INTO control_intervalos_diario 
                        (fecha, intervalo, llamadas_10m, llamadas_20m, llamadas_perdidas, llamadas_entrantes, llamadas_atendidas, dotacion_real, ausencias, sl_real, fc_acum_manual, llamadas_cierre)
                        VALUES ('{fecha_activa_str}', '{int_seleccionado}', {in_10m}, {in_20m}, {in_perd}, {in_entr}, {in_aten}, {in_dot}, 0, {in_sl_real}, 0, 0)
                    """)
                    st.success(f"✅ Datos guardados correctamente para el bloque {int_seleccionado}.")
                    st.rerun()

    # ==========================================================================
    # CONSTRUCCIÓN DE MATRIZ Y CURVA CON DATOS DISTRIBUIDOS
    # ==========================================================================
    matriz_data = []
    for i, int_lbl in enumerate(intervalos_30m):
        fc_llam = fc_list[i]
        prev_aten_row = acum_aten_interp[i - 1] if i > 0 else 0
        curr_aten_row = acum_aten_interp[i]
        curr_entr_row = acum_entr_interp[i]
        marg_entr = marg_entr_list[i]
        marg_aten = marg_aten_list[i]

        tiene_curva = (i <= last_valid_idx) and (curr_entr_row > 0 or curr_aten_row > 0)

        cumplimiento = (marg_aten - fc_llam) if i <= last_valid_idx else -fc_llam
        pct_cumpli = (cumplimiento / fc_llam) if fc_llam > 0 else 0.0

        matriz_data.append({
            "Intervalo": int_lbl,
            "Llamadas FC Interv.": fc_llam,
            "llam. ultimo intervalo": prev_aten_row,
            "llam. cierre intervalo": curr_aten_row,
            "llam. entrantes acum": curr_entr_row,
            "Lamadas Ingresadas": marg_entr,
            "Atendidas": marg_aten,
            "Plot_Ingresadas": marg_entr if tiene_curva else None,
            "Plot_Atendidas": marg_aten if tiene_curva else None,
            "Cumplimiento": cumplimiento,
            "% Cumplimiento": pct_cumpli,
            "Meta FC (Acum)": sum(fc_list[:i+1])
        })

    df_matriz_full = pd.DataFrame(matriz_data)
    if last_valid_idx >= 0:
        df_curva_reales = df_matriz_full.iloc[:last_valid_idx + 1]
    else:
        df_curva_reales = df_matriz_full.iloc[0:0]

    # ==========================================================================
    # CÁLCULO DE KPIs DEL BLOQUE ACTUAL Y ACUMULADOS
    # ==========================================================================
    datos_seleccionados = df_matriz_full.iloc[idx_sel]
    fc_marg = int(datos_seleccionados["Llamadas FC Interv."])

    if idx_sel <= last_valid_idx and (esta_guardado_seleccionado or marg_entr_list[idx_sel] > 0):
        raw_10m = int(r_prev.get("llamadas_10m", 0)) if r_prev else 0
        raw_20m = int(r_prev.get("llamadas_20m", 0)) if r_prev else 0
        kpi_perd = int(r_prev.get("llamadas_perdidas", ultimo_perd)) if r_prev else ultimo_perd
        kpi_sl = float(r_prev.get("sl_real", ultimo_sl)) if (r_prev and pd.notna(r_prev.get("sl_real"))) else ultimo_sl
        kpi_dot = int(r_prev.get("dotacion_real", ultimo_dot)) if r_prev else ultimo_dot
        
        marg_entr_actual = int(datos_seleccionados["Lamadas Ingresadas"])
        marg_aten_actual = int(datos_seleccionados["Atendidas"])
        v_entr_ac = int(datos_seleccionados["llam. entrantes acum"])
        v_aten_ac = int(datos_seleccionados["llam. cierre intervalo"])
        fc_acum = int(datos_seleccionados["Meta FC (Acum)"])

        base_bloque_aten = int(datos_seleccionados["llam. ultimo intervalo"])
        if raw_10m > base_bloque_aten and base_bloque_aten > 0:
            neto_10m = raw_10m - base_bloque_aten
            sub_10m = f"Acum: {raw_10m:,} (+{neto_10m} en 10m)"
        else:
            sub_10m = "Avance 10 min"

        if raw_20m > base_bloque_aten and base_bloque_aten > 0:
            neto_20m = raw_20m - base_bloque_aten
            sub_20m = f"Acum: {raw_20m:,} (+{neto_20m} en 20m)"
        else:
            sub_20m = "Avance 20 min"
    else:
        raw_10m = 0
        raw_20m = 0
        sub_10m = "Pendiente"
        sub_20m = "Pendiente"
        kpi_perd = ultimo_perd
        kpi_sl = ultimo_sl
        kpi_dot = ultimo_dot
        marg_entr_actual = 0
        marg_aten_actual = 0
        if last_valid_idx >= 0:
            ult_fila_guardada = df_matriz_full.iloc[last_valid_idx]
            v_entr_ac = int(ult_fila_guardada["llam. entrantes acum"])
            v_aten_ac = int(ult_fila_guardada["llam. cierre intervalo"])
            fc_acum = int(ult_fila_guardada["Meta FC (Acum)"])
        else:
            v_entr_ac = 0
            v_aten_ac = 0
            fc_acum = int(datos_seleccionados["Meta FC (Acum)"])

    cierre_intervalo = marg_aten_actual - fc_marg
    dif_fc_vs_entr = marg_entr_actual - fc_marg
    
    pct_fc_entr = (v_entr_ac / fc_acum * 100.0) if fc_acum > 0 else 0.0
    pct_fc_aten = (v_aten_ac / fc_acum * 100.0) if fc_acum > 0 else 0.0
    
    pct_dif_fc_entr = (dif_fc_vs_entr / fc_marg * 100.0) if fc_marg > 0 else 0.0
    pct_perdidas = (kpi_perd / v_entr_ac * 100.0) if v_entr_ac > 0 else 0.0

    dif_acum_fc_entr = v_entr_ac - fc_acum
    col_dif_acum = "text-green" if dif_acum_fc_entr >= 0 else "text-red"

    faltan_para_fc = fc_marg - marg_entr_actual
    if faltan_para_fc <= 0 and (esta_guardado_seleccionado or marg_entr_actual > 0):
        str_faltan = "0 (SUPERADA)"
        col_faltan = "text-green"
    else:
        str_faltan = str(faltan_para_fc)
        col_faltan = "text-yellow"

    # ==========================================================================
    # DASHBOARD KPI
    # ==========================================================================
    estado_badge = "✅ Cerrado / Guardado" if esta_guardado_seleccionado else f"⏳ En curso / Pendiente (Corte actual: {ultimo_int_guardado_nombre or 'sin registros'})"
    st.markdown(f"### ⚡ Desglose del Bloque ({int_seleccionado}) &mdash; <span style='font-size:0.9rem; color:#94A3B8;'>{estado_badge}</span>", unsafe_allow_html=True)

    col_sl = "text-green" if kpi_sl >= 85.0 else "text-yellow" if kpi_sl >= 80.0 else "text-red"
    col_cierre = "text-green" if cierre_intervalo >= 0 else "text-red"
    col_dif = "text-green" if dif_fc_vs_entr >= 0 else "text-red"

    html_fila1 = f"""
    <div class="kpi-container">
        <div class="kpi-box"><div class="kpi-title">10 MIN.</div><div class="kpi-value text-green">{raw_10m}</div><div class="kpi-sub">{sub_10m}</div></div>
        <div class="kpi-box"><div class="kpi-title">20 MIN.</div><div class="kpi-value text-green">{raw_20m}</div><div class="kpi-sub">{sub_20m}</div></div>
        <div class="kpi-box"><div class="kpi-title">CIERRE INTERVALO</div><div class="kpi-value {col_cierre}">{cierre_intervalo:+}</div><div class="kpi-sub">Atendidas vs FC</div></div>
        <div class="kpi-box"><div class="kpi-title">LLAMADAS PERDIDAS</div><div class="kpi-value text-red">{kpi_perd}</div><div class="kpi-sub">{pct_perdidas:.1f}% del total</div></div>
        <div class="kpi-box"><div class="kpi-title">NIVEL SERVICIO</div><div class="kpi-value {col_sl}">{kpi_sl:.0f}%</div><div class="kpi-sub">Global BP</div></div>
    </div>
    """
    st.markdown(html_fila1, unsafe_allow_html=True)

    st.markdown("### 📈 Tráfico del Bloque (30 Min)")

    html_fila2 = f"""
    <div class="kpi-container">
        <div class="kpi-box"><div class="kpi-title">LLAMA FC</div><div class="kpi-value text-blue">{fc_marg}</div></div>
        <div class="kpi-box"><div class="kpi-title">FC VS ENTR.</div><div class="kpi-value {col_dif}">{dif_fc_vs_entr:+}</div></div>
        <div class="kpi-box"><div class="kpi-title">% FC VS ENTR.</div><div class="kpi-value {col_dif}">{pct_dif_fc_entr:+.0f}%</div></div>
        <div class="kpi-box"><div class="kpi-title">LLAMADAS ATENDIDAS</div><div class="kpi-value text-green">{marg_aten_actual}</div></div>
        <div class="kpi-box"><div class="kpi-title">FALTAN P/ META FC</div><div class="kpi-value {col_faltan}">{str_faltan}</div></div>
        <div class="kpi-box"><div class="kpi-title">DOTACIÓN REAL</div><div class="kpi-value">{kpi_dot} / {fc_dot_bloque}</div></div>
    </div>
    """
    st.markdown(html_fila2, unsafe_allow_html=True)

    st.markdown("### 📊 Cumplimiento Acumulado del Día (Confirmado)")
    
    html_fila3 = f"""
    <div class="kpi-container">
        <div class="kpi-box"><div class="kpi-title">FC (PRONÓSTICO)</div><div class="kpi-value text-blue">{fc_acum:,}</div></div>
        <div class="kpi-box"><div class="kpi-title">LLAMADAS ENTRANTES</div><div class="kpi-value text-orange">{v_entr_ac:,}</div></div>
        <div class="kpi-box"><div class="kpi-title">DIF. PRONÓSTICO VS ENTR.</div><div class="kpi-value {col_dif_acum}">{dif_acum_fc_entr:+,}</div></div>
        <div class="kpi-box"><div class="kpi-title">% FC X LLAMADAS ENTRANTES</div><div class="kpi-value text-orange">{pct_fc_entr:.0f}%</div></div>
        <div class="kpi-box"><div class="kpi-title">LLAMADAS ATENDIDAS</div><div class="kpi-value text-green">{v_aten_ac:,}</div></div>
        <div class="kpi-box"><div class="kpi-title">% FC X LLAMADAS ATENDIDAS</div><div class="kpi-value text-green">{pct_fc_aten:.0f}%</div></div>
    </div>
    """
    st.markdown(html_fila3, unsafe_allow_html=True)

    # ==========================================================================
    # SECCIÓN: CURVA DE TRÁFICO MARGINAL
    # ==========================================================================
    st.markdown("---")
    st.markdown("### 📉 Curva de Tráfico del Día")
    st.caption("La curva distribuye inteligentemente cualquier bloque intermedio no registrado y corta en el último bloque guardado.")

    eje_x_full = df_matriz_full["Intervalo"].str.split(" - ").str[0]
    eje_x_reales = df_curva_reales["Intervalo"].str.split(" - ").str[0]

    if HAY_PLOTLY:
        fig_curva = go.Figure()
        
        fig_curva.add_trace(go.Scatter(
            x=eje_x_full, y=df_matriz_full["Llamadas FC Interv."],
            mode="lines+markers", name="Pronóstico Llamadas Entrantes",
            line=dict(color="#1F77B4", width=3), marker=dict(size=6, color="#1F77B4")
        ))

        if not df_curva_reales.empty:
            fig_curva.add_trace(go.Scatter(
                x=eje_x_reales, y=df_curva_reales["Plot_Ingresadas"], 
                mode="lines+markers", name="Llamadas Entrantes",
                line=dict(color="#FF7F0E", width=3), marker=dict(size=6, color="#FF7F0E"),
                connectgaps=True
            ))

            fig_curva.add_trace(go.Scatter(
                x=eje_x_reales, y=df_curva_reales["Plot_Atendidas"], 
                mode="lines+markers", name="Total Atendidas",
                line=dict(color="#2CA02C", width=3), marker=dict(size=6, color="#2CA02C"),
                connectgaps=True
            ))

        fig_curva.update_layout(
            template="plotly_dark", paper_bgcolor="rgba(10, 16, 28, 0.95)", plot_bgcolor="rgba(15, 23, 42, 0.95)",
            margin=dict(l=20, r=20, t=30, b=20), height=420,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            xaxis=dict(tickangle=-45, gridcolor="#1E293B"), yaxis=dict(gridcolor="#1E293B", title="Llamadas Netas (30 Min)")
        )
        st.plotly_chart(fig_curva, width="stretch", config={"displayModeBar": True})
    else:
        df_st_chart = df_matriz_full[["Intervalo", "Llamadas FC Interv."]].copy()
        df_st_chart["Lamadas Ingresadas"] = df_matriz_full["Plot_Ingresadas"].where(df_matriz_full.index <= last_valid_idx, None)
        df_st_chart["Atendidas"] = df_matriz_full["Plot_Atendidas"].where(df_matriz_full.index <= last_valid_idx, None)
        st.line_chart(df_st_chart.set_index("Intervalo")[["Llamadas FC Interv.", "Lamadas Ingresadas", "Atendidas"]], color=["#1F77B4", "#FF7F0E", "#2CA02C"], width="stretch")

    # ==========================================================================
    # REPORTES Y MATRIZ EXACTA AL EXCEL / HTML
    # ==========================================================================
    st.markdown("---")
    t_wsp, t_matriz = st.tabs(["📱 Reporte WhatsApp", "📑 Enviar al Término del Turno (Matriz)"])

    with t_wsp:
        bloque_reporte = int_seleccionado if esta_guardado_seleccionado else (ultimo_int_guardado_nombre or int_seleccionado)
        texto_wsp = f"""*📊 REPORTE INTERVALO {bloque_reporte}*

*ACUMULADOS DEL DÍA*
📞 Meta Llamadas FC: {fc_acum:,}
📥 Llamadas Entrantes: {v_entr_ac:,} (Cumplimiento: {pct_fc_entr:.0f}%)
✅ Llamadas Atendidas: {v_aten_ac:,} (Cumplimiento: {pct_fc_aten:.0f}%)

*RENDIMIENTO ESTE BLOQUE ({bloque_reporte})*
⏱️ 10 Min: {raw_10m}
⏱️ 20 Min: {raw_20m}
⏱️ Cierre Int: {cierre_intervalo:+}
❌ Llamadas Perdidas: {kpi_perd} ({pct_perdidas:.2f}%)
🎯 Nivel de Servicio Global: {kpi_sl:.1f}%

👥 Dotación Real: {kpi_dot} Real / {fc_dot_bloque} FC"""
        
        st.text_area("Copiar texto para WhatsApp:", texto_wsp, height=350)

    with t_matriz:
        st.markdown("#### 📑 Matriz Consolidada de Cierre de Turno")
        
        df_export = df_matriz_full[["Intervalo", "Llamadas FC Interv.", "llam. ultimo intervalo", "llam. cierre intervalo", "Lamadas Ingresadas", "Atendidas", "Cumplimiento", "% Cumplimiento"]].copy()
        
        def colorear_cumplimiento(valor):
            str_val = str(valor).strip()
            try:
                num = float(str_val.replace('%', '').replace(',', '.'))
            except ValueError:
                return '' 
            if num > 0:
                return 'color: #00e676; font-weight: bold;' 
            elif num < 0:
                return 'color: #ff4b4b; font-weight: bold;' 
            return ''

        df_export_html = df_export.copy()
        df_export_html["% Cumplimiento"] = df_export_html["% Cumplimiento"].apply(lambda x: f"{x:.0f}%" if pd.notna(x) else "")
        
        styler = df_export_html.style.map(colorear_cumplimiento, subset=['Cumplimiento', '% Cumplimiento'])
        try:
            styler = styler.hide(axis="index")
        except AttributeError:
            styler = styler.hide_index()
            
        html_str_styled = styler.to_html()

        c_btn1, c_btn2 = st.columns(2)
        firma_cache_matriz = f"{fecha_activa_str}_{last_valid_idx}_{acum_entr_interp[-1]}_{acum_aten_interp[-1]}_{version_datos}"
        excel_data = generar_excel_matriz_cierre(df_export, firma_cache_matriz)
        c_btn1.download_button(
            label="📥 Descargar Matriz Formateada en Excel",
            data=excel_data,
            file_name=f"Matriz_Cierre_Turno_{fecha_activa_str}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch"
        )
        
        html_print_view = f"""
        <!DOCTYPE html>
        <html lang="es">
        <head>
            <meta charset="UTF-8">
            <title>Matriz Consolidada de Cierre de Turno</title>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #1A202C; color: #E2E8F0; padding: 20px; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
                h2 {{ text-align: center; color: white; margin-bottom: 20px; font-weight: 800; }}
                table {{ width: 100%; border-collapse: collapse; font-size: 12px; text-align: center; }}
                th, td {{ border: 1px solid #2D3748; padding: 6px 4px; }}
                thead th {{ border: 1px solid #0F172A; }}
                thead th:nth-child(1) {{ background-color: #1F497D !important; color: white !important; }}
                thead th:nth-child(2), thead th:nth-child(3), thead th:nth-child(4), thead th:nth-child(5) {{ background-color: #203764 !important; color: white !important; }}
                thead th:nth-child(6), thead th:nth-child(7) {{ background-color: #FFFF00 !important; color: black !important; }}
                thead th:nth-child(8) {{ background-color: #1F497D !important; color: white !important; }}
                tbody tr:nth-child(even) {{ background-color: #1E293B; }}
                tbody tr:nth-child(odd) {{ background-color: #0F172A; }}
            </style>
        </head>
        <body>
            <h2>Matriz Consolidada de Cierre de Turno - {fecha_activa_str}</h2>
            {html_str_styled}
            <script> window.onload = function() {{ setTimeout(function(){{ window.print(); }}, 500); }}; </script>
        </body>
        </html>
        """
        
        c_btn2.download_button(
            label="🖨️ Imprimir / Capturar Pantalla (PDF)",
            data=html_print_view,
            file_name=f"Imprimir_Matriz_{fecha_activa_str}.html",
            mime="text/html",
            width="stretch"
        )

        st.markdown(f'<div class="html-matriz" style="overflow-x: auto;">{html_str_styled}</div>', unsafe_allow_html=True)