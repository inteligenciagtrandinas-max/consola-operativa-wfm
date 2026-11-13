import streamlit as str_lit
import pandas as pd
import os
import glob
import shutil
import uuid
from datetime import datetime

CARPETA_ALMACEN = "_almacen_wfm"

MAPA_TABLAS_SLOTS = {
    "login": "datos_login_logout",
    "actividad": "datos_productividad_tmo",
    "pausas": "datos_pausas",
    "extra": "datos_adicionales",
    "cybel": "datos_cybel"
}

# ==============================================================================
# CACHÉ DE RECURSO (MEMORIA COMPARTIDA ULTRARRÁPIDA)
# ==============================================================================
@str_lit.cache_resource(show_spinner=False)
def leer_excel_compartido(ruta_archivo, mtime):
    return pd.read_excel(ruta_archivo, sheet_name=None)

@str_lit.cache_data(show_spinner=False, max_entries=8)
def leer_csv_flexible(ruta_archivo, mtime):
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        for sep in (",", ";", "\t"):
            try:
                df = pd.read_csv(ruta_archivo, sep=sep, encoding=enc, low_memory=False)
                if df.shape[1] > 1:
                    return df
            except Exception:
                continue
    try:
        return pd.read_csv(ruta_archivo, sep=None, engine="python", encoding="latin-1", low_memory=False)
    except Exception:
        return pd.read_csv(ruta_archivo, low_memory=False)

def asegurar_estructura_compartimientos(con):
    os.makedirs(CARPETA_ALMACEN, exist_ok=True)
    con.execute("""
        CREATE TABLE IF NOT EXISTS registro_compartimientos_wfm (
            slot_id VARCHAR PRIMARY KEY,
            nombre_archivo VARCHAR,
            ruta_archivo VARCHAR,
            tipo_slot VARCHAR,
            fecha_operativa VARCHAR,
            actualizado_en VARCHAR,
            detalle VARCHAR
        );
    """)

def tabla_existe_con_datos(con, nombre_tabla):
    try:
        existe = con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
            [nombre_tabla]
        ).fetchone()[0] > 0
        if not existe:
            return False
        return con.execute(f"SELECT count(*) FROM {nombre_tabla}").fetchone()[0] > 0
    except Exception:
        return False

def registrar_en_compartimiento(con, slot_id, nombre_archivo, ruta_archivo, tipo_slot, fecha_op, detalle):
    ahora_str = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    con.execute("DELETE FROM registro_compartimientos_wfm WHERE slot_id = ?", [slot_id])
    con.execute(
        "INSERT INTO registro_compartimientos_wfm VALUES (?, ?, ?, ?, ?, ?, ?)",
        [slot_id, nombre_archivo, ruta_archivo, tipo_slot, fecha_op, ahora_str, detalle]
    )

# ==============================================================================
# RECONSTRUCCIÓN DE MEMORIA EXCEL Y TABLAS DUCKDB
# ==============================================================================
def reconstruir_hojas_excel_en_memoria(con):
    asegurar_estructura_compartimientos(con)
    if "compartimientos_excel" not in str_lit.session_state:
        str_lit.session_state["compartimientos_excel"] = {}

    df_reg = con.execute("""
        SELECT slot_id, ruta_archivo 
        FROM registro_compartimientos_wfm 
        WHERE tipo_slot = 'EXCEL' AND nombre_archivo != 'VACIADO_MANUAL'
    """).df()

    hojas_combinadas = {}
    hojas_intervalos = {}

    orden_slots = {"malla": 1, "bbdd": 2, "intervalos": 3}
    if not df_reg.empty:
        df_reg["orden"] = df_reg["slot_id"].map(lambda x: orden_slots.get(x, 9))
        df_reg = df_reg.sort_values("orden")

        for _, row in df_reg.iterrows():
            s_id = row["slot_id"]
            ruta = row["ruta_archivo"]
            if ruta and os.path.exists(ruta):
                try:
                    mtime = os.path.getmtime(ruta)
                    hojas = leer_excel_compartido(ruta, mtime)
                    str_lit.session_state["compartimientos_excel"][s_id] = hojas
                    hojas_combinadas.update(hojas)
                    if s_id == "intervalos" or "Cuadro de Mando" in hojas:
                        hojas_intervalos.update(hojas)
                except Exception as e:
                    print(f"Error cargando compartimiento Excel {s_id}: {e}")

    str_lit.session_state["excel_colaciones_hojas"] = hojas_combinadas
    str_lit.session_state["excel_intervalos_hojas"] = hojas_intervalos if hojas_intervalos else hojas_combinadas

def cargar_tabla_desde_df(con, df, nombre_tabla, fecha_activa_str):
    if df is None or df.empty:
        return
    df_save = df.copy()
    df_save["fecha_gestion"] = fecha_activa_str

    uid = uuid.uuid4().hex[:8]
    temp_ing = f"t_temp_ing_{uid}"

    con.execute(f"DROP TABLE IF EXISTS {nombre_tabla}")
    con.register(temp_ing, df_save)
    try:
        con.execute(f"CREATE TABLE {nombre_tabla} AS SELECT * FROM {temp_ing}")
    finally:
        try:
            con.unregister(temp_ing)
        except Exception:
            pass

    # Espejo automático entre Actividad (5) y Pausas (6) con nombres únicos
    if nombre_tabla == "datos_pausas" and not tabla_existe_con_datos(con, "datos_productividad_tmo"):
        temp_esp = f"t_temp_esp_{uid}"
        con.register(temp_esp, df_save)
        try:
            con.execute(f"CREATE TABLE datos_productividad_tmo AS SELECT * FROM {temp_esp}")
        finally:
            try:
                con.unregister(temp_esp)
            except Exception:
                pass
    elif nombre_tabla == "datos_productividad_tmo" and not tabla_existe_con_datos(con, "datos_pausas"):
        temp_esp2 = f"t_temp_esp2_{uid}"
        con.register(temp_esp2, df_save)
        try:
            con.execute(f"CREATE TABLE datos_pausas AS SELECT * FROM {temp_esp2}")
        finally:
            try:
                con.unregister(temp_esp2)
            except Exception:
                pass

def sincronizar_tablas_y_fechas_activas(con, fecha_activa_str):
    asegurar_estructura_compartimientos(con)
    df_reg = con.execute("""
        SELECT slot_id, nombre_archivo, ruta_archivo, tipo_slot, fecha_operativa
        FROM registro_compartimientos_wfm
        WHERE nombre_archivo != 'VACIADO_MANUAL'
    """).df()

    if df_reg.empty:
        return

    for _, row in df_reg.iterrows():
        s_id = row["slot_id"]
        ruta = row["ruta_archivo"]
        t_slot = row["tipo_slot"]

        if not ruta or not os.path.exists(ruta):
            con.execute("DELETE FROM registro_compartimientos_wfm WHERE slot_id = ?", [s_id])
            continue

        if t_slot == "TABLA" and s_id in MAPA_TABLAS_SLOTS:
            tabla_sql = MAPA_TABLAS_SLOTS[s_id]
            if not tabla_existe_con_datos(con, tabla_sql):
                try:
                    mtime = os.path.getmtime(ruta)
                    if ruta.lower().endswith((".csv", ".txt")):
                        df_rec = leer_csv_flexible(ruta, mtime)
                    else:
                        dict_h = leer_excel_compartido(ruta, mtime)
                        df_rec = list(dict_h.values())[0]
                    cargar_tabla_desde_df(con, df_rec, tabla_sql, fecha_activa_str)
                except Exception as e:
                    print(f"Error reconstruyendo tabla {tabla_sql}: {e}")
            else:
                try:
                    c_fecha = con.execute(f"SELECT count(*) FROM {tabla_sql} WHERE fecha_gestion = '{fecha_activa_str}'").fetchone()[0]
                    if c_fecha == 0:
                        con.execute(f"UPDATE {tabla_sql} SET fecha_gestion = '{fecha_activa_str}'")
                except Exception:
                    pass

# ==============================================================================
# PRE-CARGA AUTOMÁTICA AL ABRIR LA CONSOLA
# ==============================================================================
def precargar_archivos_locales(con, fecha_activa_str, forzar_reescaneo=False):
    asegurar_estructura_compartimientos(con)
    archivos_nuevos = []

    if forzar_reescaneo:
        con.execute("DELETE FROM registro_compartimientos_wfm WHERE nombre_archivo = 'VACIADO_MANUAL'")

    df_check_maestras = con.execute("""
        SELECT count(*) FROM registro_compartimientos_wfm 
        WHERE slot_id IN ('malla', 'bbdd') AND nombre_archivo != 'VACIADO_MANUAL'
    """).fetchone()[0]
    if df_check_maestras == 0:
        con.execute("DELETE FROM registro_compartimientos_wfm WHERE slot_id IN ('malla', 'bbdd', 'intervalos') AND nombre_archivo = 'VACIADO_MANUAL'")

    df_actuales = con.execute("SELECT slot_id, nombre_archivo, ruta_archivo FROM registro_compartimientos_wfm").df()
    slots_registrados = {}
    if not df_actuales.empty:
        for _, r in df_actuales.iterrows():
            if r["nombre_archivo"] == "VACIADO_MANUAL":
                slots_registrados[r["slot_id"]] = "VACIADO_MANUAL"
            elif r["ruta_archivo"] and os.path.exists(r["ruta_archivo"]):
                slots_registrados[r["slot_id"]] = r["ruta_archivo"]

    # 1. Auto-asignar libros Excel de la carpeta local
    for ruta_excel in sorted(glob.glob("*.xls*")):
        nombre_base = os.path.basename(ruta_excel)
        if nombre_base.startswith("~$"):
            continue
        nom_up = nombre_base.upper()

        slot_destino = None
        if ("BDD" in nom_up and "CLIENTE" not in nom_up) and "malla" not in slots_registrados:
            slot_destino = "malla"
        elif any(k in nom_up for k in ["CLIENTE", "FINAL", "SEMANAL", "V2"]) and "bbdd" not in slots_registrados:
            slot_destino = "bbdd"
        elif any(k in nom_up for k in ["INTERVALO", "MANDO"]) and "intervalos" not in slots_registrados:
            slot_destino = "intervalos"
        elif "malla" not in slots_registrados:
            slot_destino = "malla"
        elif "bbdd" not in slots_registrados:
            slot_destino = "bbdd"

        if slot_destino:
            try:
                mtime = os.path.getmtime(ruta_excel)
                hojas = leer_excel_compartido(ruta_excel, mtime)
                detalle = f"{len(hojas)} pestañas activas"
                registrar_en_compartimiento(con, slot_destino, nombre_base, ruta_excel, "EXCEL", "PERMANENTE", detalle)
                slots_registrados[slot_destino] = ruta_excel
                archivos_nuevos.append(nombre_base)
            except Exception as e:
                print(f"Error vinculando Excel {nombre_base}: {e}")

    # 2. Auto-asignar CSV locales de la carpeta raíz
    for ruta_csv in sorted(glob.glob("*.csv")):
        nombre_base = os.path.basename(ruta_csv)
        nom_low = nombre_base.lower()

        slot_csv, tabla_destino = None, None
        if "login" in nom_low or "logout" in nom_low:
            slot_csv, tabla_destino = "login", "datos_login_logout"
        elif "activity" in nom_low or "tmo" in nom_low or "productividad" in nom_low:
            slot_csv, tabla_destino = "actividad", "datos_productividad_tmo"
        elif "state" in nom_low or "pausa" in nom_low:
            slot_csv, tabla_destino = "pausas", "datos_pausas"
        elif "cybel" in nom_low:
            slot_csv, tabla_destino = "cybel", "datos_cybel"

        if slot_csv and slot_csv not in slots_registrados:
            try:
                mtime = os.path.getmtime(ruta_csv)
                df_c = leer_csv_flexible(ruta_csv, mtime)
                if not df_c.empty:
                    cargar_tabla_desde_df(con, df_c, tabla_destino, fecha_activa_str)
                    detalle = f"{len(df_c):,} registros ({fecha_activa_str})"
                    registrar_en_compartimiento(con, slot_csv, nombre_base, ruta_csv, "TABLA", fecha_activa_str, detalle)
                    slots_registrados[slot_csv] = ruta_csv
                    archivos_nuevos.append(nombre_base)
            except Exception as e:
                print(f"Error vinculando CSV {nombre_base}: {e}")

    reconstruir_hojas_excel_en_memoria(con)
    sincronizar_tablas_y_fechas_activas(con, fecha_activa_str)

    if archivos_nuevos:
        str_lit.session_state["version_datos"] = str_lit.session_state.get("version_datos", 1) + 1

    return archivos_nuevos

# ==============================================================================
# FUNCIONES DE GUARDADO Y VACIADO DE COMPARTIMIENTOS
# ==============================================================================
def guardar_archivo_en_slot(con, archivo_subido, slot_id, tipo_slot, tabla_sql, fecha_activa_str):
    asegurar_estructura_compartimientos(con)
    carpeta_slot = os.path.join(CARPETA_ALMACEN, slot_id)
    os.makedirs(carpeta_slot, exist_ok=True)
    for f_old in glob.glob(os.path.join(carpeta_slot, "*")):
        try:
            os.remove(f_old)
        except Exception:
            pass

    sello = int(datetime.now().timestamp() * 1000)
    nombre_limpio = os.path.basename(archivo_subido.name)
    ruta_destino = os.path.join(carpeta_slot, f"{sello}_{nombre_limpio}")
    with open(ruta_destino, "wb") as f_out:
        f_out.write(archivo_subido.getbuffer())

    if tipo_slot == "EXCEL":
        mtime = os.path.getmtime(ruta_destino)
        hojas = leer_excel_compartido(ruta_destino, mtime)
        detalle = f"{len(hojas)} pestañas activas"
        registrar_en_compartimiento(con, slot_id, nombre_limpio, ruta_destino, "EXCEL", "PERMANENTE", detalle)
        reconstruir_hojas_excel_en_memoria(con)
        if slot_id in ["malla", "bbdd"]:
            try:
                con.execute("DELETE FROM maestro_bdd_personal")
            except Exception:
                pass
        return f"✅ {nombre_limpio} guardado con éxito ({detalle})."
    else:
        mtime = os.path.getmtime(ruta_destino)
        if nombre_limpio.lower().endswith((".csv", ".txt")):
            df = leer_csv_flexible(ruta_destino, mtime)
        else:
            dict_h = leer_excel_compartido(ruta_destino, mtime)
            df = list(dict_h.values())[0]

        cargar_tabla_desde_df(con, df, tabla_sql, fecha_activa_str)
        detalle = f"{len(df):,} registros ({fecha_activa_str})"
        registrar_en_compartimiento(con, slot_id, nombre_limpio, ruta_destino, "TABLA", fecha_activa_str, detalle)
        return f"✅ {nombre_limpio} guardado con éxito ({detalle})."

def vaciar_compartimiento_individual(con, slot_id, tipo_slot, tabla_sql):
    registrar_en_compartimiento(con, slot_id, "VACIADO_MANUAL", "", tipo_slot, "", "Vaciado manualmente")
    carpeta_slot = os.path.join(CARPETA_ALMACEN, slot_id)
    if os.path.exists(carpeta_slot):
        for f_old in glob.glob(os.path.join(carpeta_slot, "*")):
            try:
                os.remove(f_old)
            except Exception:
                pass

    if tipo_slot == "EXCEL":
        reconstruir_hojas_excel_en_memoria(con)
        if slot_id in ["malla", "bbdd"]:
            try:
                con.execute("DELETE FROM maestro_bdd_personal")
            except Exception:
                pass
    elif tabla_sql:
        try:
            con.execute(f"DROP TABLE IF EXISTS {tabla_sql}")
        except Exception:
            pass

    str_lit.cache_data.clear()
    str_lit.session_state["version_datos"] = str_lit.session_state.get("version_datos", 1) + 1

def reiniciar_intervalos_y_login_del_dia(con, fecha_activa_str):
    vaciar_compartimiento_individual(con, "login", "TABLA", "datos_login_logout")
    try:
        con.execute(f"DELETE FROM control_intervalos_diario WHERE fecha = '{fecha_activa_str}'")
    except Exception:
        pass
    str_lit.cache_data.clear()
    str_lit.session_state["version_datos"] = str_lit.session_state.get("version_datos", 1) + 1

# ==============================================================================
# RENDERIZADO DEL MÓDULO DE INGESTA
# ==============================================================================
def renderizar_ingesta(con, fecha_activa_str):
    str_lit.markdown("""
    <style>
        .slot-active-card {
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.2) 0%, rgba(15, 23, 42, 0.92) 100%);
            border: 1px solid rgba(16, 185, 129, 0.55);
            border-left: 5px solid #10B981;
            border-radius: 12px;
            padding: 10px 14px;
            margin-bottom: 8px;
        }
        .slot-empty-card {
            background: rgba(15, 23, 42, 0.6);
            border: 1px dashed rgba(148, 163, 184, 0.35);
            border-left: 5px solid #64748B;
            border-radius: 12px;
            padding: 10px 14px;
            margin-bottom: 8px;
        }
    </style>
    <div class="section-divider" style="margin-bottom: 18px;">
        <h2 style="margin-top: 0; color: #FFFFFF; font-size: 2.2rem; font-weight: 900;">⚙️ Centro de Ingesta de Datos WFM</h2>
        <p style="color: #94A3B8; font-size: 1.05rem; margin-bottom: 0;">
            Tus Bases Maestras (1, 2 y 3) se cargan automáticamente y quedan fijas en su compartimiento. Para subir o sustituir cualquier archivo manual, selecciónalo y presiona el botón verde <b>PROCESAR Y GUARDAR ARCHIVOS</b>.
        </p>
    </div>
    """, unsafe_allow_html=True)

    if "ingesta_inicial_verificada" not in str_lit.session_state:
        archivos_autocargados = precargar_archivos_locales(con, fecha_activa_str, forzar_reescaneo=False)
        str_lit.session_state["ingesta_inicial_verificada"] = True
        if archivos_autocargados:
            str_lit.toast(f"🤖 Pre-cargados en memoria: {', '.join(archivos_autocargados)}", icon="✅")
    elif not str_lit.session_state.get("excel_colaciones_hojas"):
        reconstruir_hojas_excel_en_memoria(con)

    if "mensajes_exito_ingesta" in str_lit.session_state and str_lit.session_state["mensajes_exito_ingesta"]:
        for msg in str_lit.session_state["mensajes_exito_ingesta"]:
            str_lit.success(msg)
        str_lit.session_state["mensajes_exito_ingesta"] = []

    c_qr1, c_qr2, c_qr3 = str_lit.columns(3)
    with c_qr1:
        if str_lit.button("🔄 Reiniciar SOLO Intervalos + Login/Logout", use_container_width=True):
            reiniciar_intervalos_y_login_del_dia(con, fecha_activa_str)
            str_lit.session_state["mensajes_exito_ingesta"] = [f"✅ Intervalos del día ({fecha_activa_str}) y Login/Logout reiniciados a cero. Las Bases Maestras 1, 2 y 3 siguen activas."]
            str_lit.rerun()

    with c_qr2:
        if str_lit.button("🌅 Limpiar Reportes Diarios (4 al 8)", use_container_width=True):
            reiniciar_intervalos_y_login_del_dia(con, fecha_activa_str)
            for s_dia, t_sql in [("actividad", "datos_productividad_tmo"), ("pausas", "datos_pausas"), ("extra", "datos_adicionales"), ("cybel", "datos_cybel")]:
                vaciar_compartimiento_individual(con, s_dia, "TABLA", t_sql)
            str_lit.session_state["mensajes_exito_ingesta"] = ["✅ Todos los reportes diarios (4 al 8) fueron limpiados. Tus Bases Maestras (1, 2 y 3) permanecen intactas."]
            str_lit.rerun()

    with c_qr3:
        if str_lit.button("🔍 Restaurar Archivos Locales de la Carpeta", use_container_width=True):
            nuevos = precargar_archivos_locales(con, fecha_activa_str, forzar_reescaneo=True)
            str_lit.cache_data.clear()
            str_lit.session_state["version_datos"] = str_lit.session_state.get("version_datos", 1) + 1
            str_lit.session_state["mensajes_exito_ingesta"] = [f"✅ Se restauraron y vincularon los archivos locales de la carpeta ({len(nuevos)} archivos detectados)."]
            str_lit.rerun()

    str_lit.markdown("<hr style='border: 1px solid rgba(255,255,255,0.08); margin: 15px 0;'>", unsafe_allow_html=True)

    df_slots = con.execute("SELECT * FROM registro_compartimientos_wfm").df()
    mapa_slots = {r["slot_id"]: r.to_dict() for _, r in df_slots.iterrows()} if not df_slots.empty else {}

    def mostrar_estado_compartimiento(slot_id, titulo, tipo_slot, tabla_sql=None):
        info = mapa_slots.get(slot_id)
        esta_activo = (
            info is not None
            and info.get("nombre_archivo") != "VACIADO_MANUAL"
            and info.get("ruta_archivo")
            and os.path.exists(str(info.get("ruta_archivo")))
        )
        if esta_activo:
            str_lit.markdown(f"""
            <div class="slot-active-card">
                <div style="font-size: 0.74rem; color: #34D399; font-weight: 800; text-transform: uppercase;">
                    ✅ {titulo} — ACTIVO EN MEMORIA
                </div>
                <div style="font-size: 0.92rem; color: #F8FAFC; font-weight: 800; margin-top: 3px; word-break: break-all;">
                    📄 {info['nombre_archivo']}
                </div>
                <div style="font-size: 0.75rem; color: #CBD5E1; margin-top: 2px;">
                    📊 {info['detalle']} &bull; 🕒 {info['actualizado_en']}
                </div>
            </div>
            """, unsafe_allow_html=True)
            if str_lit.button(f"🗑️ Quitar de {titulo[:2]}", key=f"btn_del_{slot_id}", use_container_width=True):
                vaciar_compartimiento_individual(con, slot_id, tipo_slot, tabla_sql)
                str_lit.session_state["mensajes_exito_ingesta"] = [f"🗑️ Se quitó el archivo del compartimiento {titulo}."]
                str_lit.rerun()
        else:
            str_lit.markdown(f"""
            <div class="slot-empty-card">
                <div style="font-size: 0.74rem; color: #94A3B8; font-weight: 800; text-transform: uppercase;">
                    ⚪ {titulo} — COMPARTIMIENTO VACÍO
                </div>
                <div style="font-size: 0.82rem; color: #CBD5E1; margin-top: 3px;">
                    Selecciona un archivo abajo y presiona Procesar
                </div>
            </div>
            """, unsafe_allow_html=True)

    str_lit.markdown("<h4 style='color: #818CF8; margin-bottom: 12px;'>📊 Bases Maestras de Planificación (Permanentes)</h4>", unsafe_allow_html=True)
    c1, c2, c3 = str_lit.columns(3)
    with c1:
        mostrar_estado_compartimiento("malla", "1️⃣ Malla BDD y Turnos", "EXCEL")
        arch_malla = str_lit.file_uploader("1️⃣ Malla BDD y Turnos (Excel)", type=["xlsx", "xls", "xlsm"], key="up_malla")
    with c2:
        mostrar_estado_compartimiento("bbdd", "2️⃣ BBDD Cliente Final", "EXCEL")
        arch_bbdd = str_lit.file_uploader("2️⃣ BBDD Cliente Final (Semanal)", type=["xlsx", "xls", "xlsm"], key="up_bbdd")
    with c3:
        mostrar_estado_compartimiento("intervalos", "3️⃣ Cuadro de Mando / Intervalos", "EXCEL")
        arch_intervalos = str_lit.file_uploader("3️⃣ Cuadro de Mando / Intervalos", type=["xlsx", "xls", "xlsm"], key="up_inter")

    str_lit.markdown("<br>", unsafe_allow_html=True)

    str_lit.markdown(f"<h4 style='color: #34D399; margin-bottom: 12px;'>📞 Reportes Operativos Bright Pattern (Día: {fecha_activa_str})</h4>", unsafe_allow_html=True)
    c4, c5, c6 = str_lit.columns(3)
    with c4:
        mostrar_estado_compartimiento("login", "4️⃣ BP Login/Logout", "TABLA", "datos_login_logout")
        arch_login = str_lit.file_uploader("4️⃣ BP Login/Logout (Sesiones)", type=["csv", "txt"], key="up_log")
    with c5:
        mostrar_estado_compartimiento("actividad", "5️⃣ BP Agent Activity", "TABLA", "datos_productividad_tmo")
        arch_actividad = str_lit.file_uploader("5️⃣ BP Agent Activity (Productividad)", type=["csv", "txt"], key="up_act")
    with c6:
        mostrar_estado_compartimiento("pausas", "6️⃣ BP Agent State", "TABLA", "datos_pausas")
        arch_pausas = str_lit.file_uploader("6️⃣ BP Agent State (Pausas y Baños)", type=["csv", "txt"], key="up_pau")

    str_lit.markdown("<br>", unsafe_allow_html=True)

    str_lit.markdown("<h4 style='color: #FBBF24; margin-bottom: 12px;'>📎 Anexos y Reportes Cybel</h4>", unsafe_allow_html=True)
    c7, c10 = str_lit.columns(2)
    with c7:
        mostrar_estado_compartimiento("extra", "7️⃣ Base Complementaria", "TABLA", "datos_adicionales")
        arch_extra = str_lit.file_uploader("7️⃣ Base Complementaria (Opcional)", type=["csv", "xlsx", "xls", "xlsm"], key="up_ext")
    with c10:
        mostrar_estado_compartimiento("cybel", "8️⃣ Exportación Cybel", "TABLA", "datos_cybel")
        arch_cybel = str_lit.file_uploader("8️⃣ Exportación CSV / XLS Cybel", type=["csv", "xlsx", "xls", "xlsm"], key="up_cyb")

    str_lit.markdown("<br>", unsafe_allow_html=True)

    if str_lit.button("🚀 PROCESAR Y GUARDAR ARCHIVOS SUBIDOS", use_container_width=True, type="primary"):
        mensajes = []
        with str_lit.spinner("⏳ Guardando archivos en sus compartimientos y actualizando base de datos..."):
            if arch_malla is not None:
                mensajes.append(guardar_archivo_en_slot(con, arch_malla, "malla", "EXCEL", None, fecha_activa_str))
            if arch_bbdd is not None:
                mensajes.append(guardar_archivo_en_slot(con, arch_bbdd, "bbdd", "EXCEL", None, fecha_activa_str))
            if arch_intervalos is not None:
                mensajes.append(guardar_archivo_en_slot(con, arch_intervalos, "intervalos", "EXCEL", None, fecha_activa_str))
            if arch_login is not None:
                mensajes.append(guardar_archivo_en_slot(con, arch_login, "login", "TABLA", "datos_login_logout", fecha_activa_str))
            if arch_actividad is not None:
                mensajes.append(guardar_archivo_en_slot(con, arch_actividad, "actividad", "TABLA", "datos_productividad_tmo", fecha_activa_str))
            if arch_pausas is not None:
                mensajes.append(guardar_archivo_en_slot(con, arch_pausas, "pausas", "TABLA", "datos_pausas", fecha_activa_str))
            if arch_extra is not None:
                mensajes.append(guardar_archivo_en_slot(con, arch_extra, "extra", "TABLA", "datos_adicionales", fecha_activa_str))
            if arch_cybel is not None:
                mensajes.append(guardar_archivo_en_slot(con, arch_cybel, "cybel", "TABLA", "datos_cybel", fecha_activa_str))

            if not mensajes:
                sincronizar_tablas_y_fechas_activas(con, fecha_activa_str)
                reconstruir_hojas_excel_en_memoria(con)
                mensajes.append("✅ Todos los compartimientos activos fueron verificados y sincronizados con éxito.")

            str_lit.cache_data.clear()
            str_lit.session_state["version_datos"] = str_lit.session_state.get("version_datos", 1) + 1
            str_lit.session_state["mensajes_exito_ingesta"] = mensajes
        str_lit.rerun()
