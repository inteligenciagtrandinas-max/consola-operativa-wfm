import streamlit as st
import pandas as pd
import duckdb
from datetime import datetime
import re

try:
    import plotly.graph_objects as go
    HAY_PLOTLY = True
except ImportError:
    HAY_PLOTLY = False

# ==============================================================================
# FUNCIONES AUXILIARES DE LIMPIEZA Y FORMATO
# ==============================================================================
def normalizar_agente(first_name, last_name, fallback_agent):
    if pd.notna(first_name) and pd.notna(last_name):
        nombre = f"{str(first_name).strip()} {str(last_name).strip()}"
    elif pd.notna(fallback_agent):
        nombre = str(fallback_agent).strip()
    else:
        return "DESCONOCIDO"
    return re.sub(r'\s+', ' ', nombre).upper()

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

# ==============================================================================
# MOTOR CACHEADO DE PROCESAMIENTO DE PAUSAS (CERO ESCANEO CON _con)
# ==============================================================================
@st.cache_data(show_spinner=False, max_entries=4)
def obtener_pausas_procesadas(_con, fecha_activa_str, tipo_vista, version_datos):
    df_raw = pd.DataFrame()
    mes_actual = fecha_activa_str[:7]
    
    try:
        hay_tmo = _con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'datos_productividad_tmo'").fetchone()[0] > 0
        if hay_tmo:
            if "Diario" in tipo_vista:
                df_raw = _con.execute(f"SELECT * FROM datos_productividad_tmo WHERE fecha_gestion = '{fecha_activa_str}'").df()
            else:
                df_raw = _con.execute(f"SELECT * FROM datos_productividad_tmo WHERE fecha_gestion LIKE '{mes_actual}%'").df()
    except: pass

    if df_raw.empty:
        return pd.DataFrame()

    cols = {c.lower().strip().replace(' ', '_'): c for c in df_raw.columns}
    
    c_fname = cols.get('first_name')
    c_lname = cols.get('last_name')
    c_agent = next((cols[cols_k] for cols_k in cols if any(k in cols_k for k in ['agent', 'agente', 'nombre'])), None)
    c_team = next((cols[cols_k] for cols_k in cols if any(k in cols_k for k in ['team', 'area', 'equipo'])), None)
    c_act = cols.get('activity')
    c_det = next((cols[cols_k] for cols_k in cols if any(k in cols_k for k in ['detail', 'estado', 'status'])), None)
    c_dur = next((cols[cols_k] for cols_k in cols if any(k in cols_k for k in ['duration', 'duracion', 'duración', 'tiempo'])), None)
    c_start = next((cols[cols_k] for cols_k in cols if any(k in cols_k for k in ['start', 'timestamp', 'fecha_inicio'])), None)
    
    if c_fname and c_lname:
        df_raw['Agente_Limpio'] = (df_raw[c_fname].fillna('').astype(str).str.strip() + ' ' + df_raw[c_lname].fillna('').astype(str).str.strip()).str.replace(r'\s+', ' ', regex=True).str.strip().str.upper()
        df_raw.loc[df_raw['Agente_Limpio'] == '', 'Agente_Limpio'] = "DESCONOCIDO"
    elif c_agent:
        df_raw['Agente_Limpio'] = df_raw[c_agent].fillna('DESCONOCIDO').astype(str).str.replace(r'\s+', ' ', regex=True).str.strip().str.upper()
    else:
        df_raw['Agente_Limpio'] = "DESCONOCIDO"
    
    df_raw['Area'] = df_raw[c_team].fillna("GENERAL").astype(str).str.strip().str.upper() if c_team else "GENERAL"
    
    if c_start:
        df_raw['start_dt'] = pd.to_datetime(df_raw[c_start], dayfirst=True, errors='coerce')
        df_raw['Intervalo_30m'] = df_raw['start_dt'].dt.floor('30min').dt.strftime('%H:%M')
        df_raw.loc[df_raw['start_dt'].isna(), 'Intervalo_30m'] = "--:--"
    else:
        df_raw['Intervalo_30m'] = "--:--"

    def determinar_estado(row):
        act = str(row.get(c_act, '')).strip().upper() if c_act else ""
        det = str(row.get(c_det, '')).strip().upper() if c_det else ""
        
        if act in ['INBOUND_CALL', 'OUTBOUND_CALL', 'CALL']: return "Llamada"
        elif act == 'READY': return "Disponible"
        elif act == 'NOT_READY':
            if det and det not in ['NAN', 'NONE', '']: return det
            return "No Listo (Sin Motivo)"
        return det if det and det not in ['NAN', 'NONE', ''] else (act if act else "AUXILIAR")

    df_raw['Estado_Auxiliar_Raw'] = df_raw.apply(determinar_estado, axis=1)
    
    dic_estados = {
        'BANO': 'Baño', 'BAÑO': 'Baño', 
        'BREAK': 'Break', 'COLACION': 'Colación', 
        'FEEDBACK': 'Feedback', 'CAPACITACION': 'Capacitación', 'CAPACITACIÓN': 'Capacitación',
        'REUNION': 'Reunión', 'PROBLEMA TECNICO': 'Problema Técnico', 'SOPORTE': 'Soporte TI',
        'NO LISTO (SIN MOTIVO)': 'No Listo (Sin Motivo)'
    }
    df_raw['Estado_Auxiliar'] = df_raw['Estado_Auxiliar_Raw'].apply(lambda x: dic_estados.get(x, x.title()))
    
    df_raw['Duracion_Seg'] = df_raw[c_dur].apply(a_segundos) if c_dur else 0
    df_raw['Excede_10Min'] = (df_raw['Duracion_Seg'] > 600).astype(int)

    df_pausas = df_raw[~df_raw["Estado_Auxiliar"].isin(["Llamada", "Disponible"])].copy()
    return df_pausas

# ==============================================================================
# MÓDULO PRINCIPAL DE MONITOREO DE PAUSAS Y AUXILIARES
# ==============================================================================
def renderizar_modulo_monitor_pausas(con, fecha_activa_str):
    st.markdown("""
    <style>
        .header-section-aux {
            background: linear-gradient(90deg, rgba(139, 92, 246, 0.25) 0%, rgba(15, 23, 42, 0.85) 100%);
            border-left: 5px solid #8B5CF6; padding: 10px 16px; border-radius: 8px;
            margin: 24px 0 10px 0; display: flex; align-items: center; justify-content: space-between;
        }
        .header-section-curve {
            background: linear-gradient(90deg, rgba(56, 189, 248, 0.25) 0%, rgba(15, 23, 42, 0.85) 100%);
            border-left: 5px solid #38BDF8; padding: 10px 16px; border-radius: 8px;
            margin: 24px 0 10px 0; display: flex; align-items: center; justify-content: space-between;
        }
        .kpi-container { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
        .kpi-box { background: linear-gradient(145deg, #131D2E 0%, #1C273C 100%); border: 1px solid #2A3952; border-radius: 8px; padding: 12px 10px; flex: 1; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3); display: flex; flex-direction: column; justify-content: center; }
        .kpi-title { font-size: 0.75rem; color: #94A3B8; text-transform: uppercase; font-weight: 800; margin-bottom: 4px; letter-spacing: 0.5px; }
        .kpi-value { font-size: 1.8rem; font-weight: 900; color: #F8FAFC; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%); border: 1px solid #334155; border-radius: 12px; padding: 14px 20px; height: 95px; display: flex; flex-direction: column; justify-content: center; margin-bottom: 15px;">
        <div style="font-size: 0.8rem; letter-spacing: 0.08em; color: #94A3B8; text-transform: uppercase;">
            Consola WFM &bull; Operación WFM
        </div>
        <div style="font-size: 1.65rem; font-weight: 800; color: #F8FAFC; margin-top: 2px;">
            Analítica de Estados Auxiliares
        </div>
    </div>
    """, unsafe_allow_html=True)

    tipo_vista = st.radio("Temporalidad de Análisis:", ["Diario (Día Seleccionado)", "Mensual (Todo el mes activo)"], horizontal=True, key="radio_temp_pausas")

    version_datos = st.session_state.get("version_datos", 1)
    df_pausas = obtener_pausas_procesadas(con, fecha_activa_str, tipo_vista, version_datos)

    if df_pausas.empty:
        st.warning(f"⚠️ Faltan datos operativos. Sube el archivo 'Agent Activity' en la Ingesta de Datos.")
        return

    st.markdown("### 🔎 Filtros de Segmentación Auxiliar")
    c_f1, c_f2, c_f3 = st.columns(3)
    
    areas_disp = ["TODAS"] + sorted(df_pausas["Area"].unique().tolist())
    area_sel = c_f1.selectbox("🏢 Equipo / Área:", areas_disp, key="sel_area_pausas")
    
    agentes_disp = ["TODOS"] + sorted(df_pausas["Agente_Limpio"].unique().tolist())
    agente_sel = c_f2.selectbox("👤 Ejecutivo:", agentes_disp, key="sel_agente_pausas")
    
    estados_disp = ["TODOS LOS AUXILIARES"] + sorted(df_pausas["Estado_Auxiliar"].unique().tolist())
    estado_sel = c_f3.selectbox("🏷️ Estado Específico:", estados_disp, key="sel_estado_pausas")

    df_flt = df_pausas.copy()
    if area_sel != "TODAS": df_flt = df_flt[df_flt["Area"] == area_sel]
    if agente_sel != "TODOS": df_flt = df_flt[df_flt["Agente_Limpio"] == agente_sel]
    if estado_sel != "TODOS LOS AUXILIARES": df_flt = df_flt[df_flt["Estado_Auxiliar"] == estado_sel]

    if df_flt.empty:
        st.info("ℹ️ No hay registros de auxiliares para los filtros seleccionados.")
        return

    total_reg = len(df_flt)
    total_excesos = int(df_flt["Excede_10Min"].sum())
    total_estados = df_flt["Estado_Auxiliar"].nunique()
    tiempo_total_seg = int(df_flt["Duracion_Seg"].sum())

    st.markdown(f"""
    <div class="kpi-container">
        <div class="kpi-box"><div class="kpi-title">Pausas del Servicio</div><div class="kpi-value text-blue">{total_reg:,}</div></div>
        <div class="kpi-box"><div class="kpi-title">Alertas > 10 Min</div><div class="kpi-value text-orange">{total_excesos}</div></div>
        <div class="kpi-box"><div class="kpi-title">Tipos de Auxiliares</div><div class="kpi-value text-yellow">{total_estados}</div></div>
        <div class="kpi-box"><div class="kpi-title">Tiempo Total (HH:MM:SS)</div><div class="kpi-value text-red">{formatear_segundos(tiempo_total_seg)}</div></div>
    </div>
    """, unsafe_allow_html=True)

    df_agrupado = df_flt.groupby(["Agente_Limpio", "Estado_Auxiliar"]).agg(
        Frecuencia=('Estado_Auxiliar', 'count'),
        Veces_Exceso=('Excede_10Min', 'sum'),
        Tiempo_Total_Seg=('Duracion_Seg', 'sum')
    ).reset_index()

    df_agrupado["Tiempo Total (HH:MM:SS)"] = df_agrupado["Tiempo_Total_Seg"].apply(formatear_segundos)
    df_agrupado = df_agrupado.sort_values(by=["Frecuencia", "Tiempo_Total_Seg"], ascending=[False, False])
    
    df_display = df_agrupado[["Agente_Limpio", "Estado_Auxiliar", "Frecuencia", "Veces_Exceso", "Tiempo Total (HH:MM:SS)", "Tiempo_Total_Seg"]].copy()
    df_display.rename(columns={
        "Agente_Limpio": "Ejecutivo", 
        "Estado_Auxiliar": "Motivo / Auxiliar", 
        "Frecuencia": "Cant. de Veces",
        "Veces_Exceso": "Veces > 10 Min"
    }, inplace=True)

    def colorear_alertas(row):
        motivo = str(row['Motivo / Auxiliar']).upper()
        veces = row['Cant. de Veces']
        excesos = row['Veces > 10 Min']
        tiempo = row['Tiempo_Total_Seg']
        
        mult = 20 if 'Mensual' in tipo_vista else 1
        styles = [''] * len(row)
        if motivo == "BAÑO":
            if veces >= (4 * mult) or excesos > 0 or tiempo > (20 * 60 * mult): 
                return ['background-color: rgba(220, 38, 38, 0.35); color: #FFFFFF;'] * len(row)
        elif motivo == "NO LISTO (SIN MOTIVO)":
            if veces >= (10 * mult) or tiempo > (15 * 60 * mult): 
                return ['background-color: rgba(217, 119, 6, 0.35); color: #FFFFFF;'] * len(row)
        return styles

    st.caption("📝 *Los excesos (ej. Baño > 10 min o frecuencia excesiva) se resaltan en **Rojo** para auditoría.*")
    df_show = df_display.drop(columns=["Tiempo_Total_Seg"])
    
    try:
        styled_df = df_display.style.apply(colorear_alertas, axis=1)
        styled_df = styled_df.hide(axis="columns", subset=["Tiempo_Total_Seg"]).hide(axis="index")
        st.dataframe(styled_df, use_container_width=True, height=450)
    except Exception:
        st.dataframe(df_show, use_container_width=True, hide_index=True)

    st.markdown("""
    <div class="header-section-curve">
        <div>
            <span style="font-size: 1.15rem; font-weight: 800; color: #38BDF8;">📉 Curva de Intervalo: Tráfico (Cliente Final) vs Auxiliares</span>
        </div>
        <span style="background: rgba(56, 189, 248, 0.2); color: #38BDF8; padding: 3px 10px; border-radius: 6px; font-size: 0.75rem; font-weight: 700;">BLOQUES 30 MIN</span>
    </div>
    """, unsafe_allow_html=True)

    if HAY_PLOTLY:
        df_int = pd.DataFrame()
        try:
            hay_int = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'control_intervalos_diario'").fetchone()[0] > 0
            if hay_int:
                df_int = con.execute(f"SELECT * FROM control_intervalos_diario WHERE fecha = '{fecha_activa_str}' ORDER BY intervalo").df()
        except: pass

        df_pausas_int = df_flt[df_flt["Intervalo_30m"] != "--:--"].groupby("Intervalo_30m").agg(
            Eventos_Auxiliares=('Estado_Auxiliar', 'count')
        ).reset_index()

        if not df_pausas_int.empty:
            fig_curve = go.Figure()
            fig_curve.add_trace(go.Bar(
                x=df_pausas_int["Intervalo_30m"], y=df_pausas_int["Eventos_Auxiliares"],
                name="Veces en Auxiliar", marker_color="rgba(139, 92, 246, 0.7)", yaxis="y1"
            ))

            if not df_int.empty:
                df_int["Hora_Ini"] = df_int["intervalo"].str.split(" - ").str[0]
                df_cruce_graf = pd.merge(df_pausas_int, df_int, left_on="Intervalo_30m", right_on="Hora_Ini", how="outer").sort_values(by="Intervalo_30m")
                df_cruce_graf["Eventos_Auxiliares"] = df_cruce_graf["Eventos_Auxiliares"].fillna(0)
                
                fig_curve.add_trace(go.Scatter(
                    x=df_cruce_graf["Hora_Ini"], y=df_cruce_graf["llamadas_entrantes"], 
                    mode="lines+markers", name="Llamadas Entrantes (Cliente Final)",
                    line=dict(color="#38BDF8", width=3, shape="spline"), yaxis="y2"
                ))

            fig_curve.update_layout(
                template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", 
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), 
                xaxis=dict(title="Intervalo (30 Min)"), 
                yaxis=dict(title="Cant. de Auxiliares", side="left", showgrid=False), 
                yaxis2=dict(title="Volumen de Llamadas", side="right", overlaying="y", showgrid=True, gridcolor="#1E293B"), 
                margin=dict(l=20, r=20, t=30, b=20), height=400
            )
            st.plotly_chart(fig_curve, use_container_width=True)
        else:
            st.info("No hay suficientes datos de tiempo para graficar la curva de auxiliares hoy.")