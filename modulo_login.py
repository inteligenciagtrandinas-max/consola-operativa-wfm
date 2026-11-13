import streamlit as st
import hashlib
import modulo_usuarios

def renderizar_login(con):
    try:
        modulo_usuarios.inicializar_tabla_usuarios(con)
    except Exception:
        pass

    st.markdown("""
    <style>
        .login-card {
            background: rgba(15, 23, 42, 0.90);
            border: 2px solid rgba(56, 189, 248, 0.40);
            border-radius: 22px;
            padding: 38px 32px;
            box-shadow: 0 16px 40px rgba(0, 0, 0, 0.55);
            text-align: center;
            margin-top: 40px;
        }
        .login-title {
            font-size: 2.0rem;
            font-weight: 900;
            color: #F8FAFC;
            margin-bottom: 6px;
        }
        .login-sub {
            font-size: 0.96rem;
            color: #38BDF8;
            font-weight: 700;
            margin-bottom: 24px;
        }
    </style>
    """, unsafe_allow_html=True)

    _, col_centro, _ = st.columns([1.2, 1.3, 1.2])

    with col_centro:
        st.markdown("""
        <div class="login-card">
            <div style="font-size: 3.2rem; margin-bottom: 8px;">💧⚙️</div>
            <div class="login-title">Consola Maestra GTR</div>
            <div class="login-sub">Aguas Andinas &bull; Inteligencia Operativa y WFM</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

        with st.form("form_login_wfm"):
            usuario_in = st.text_input("👤 Usuario:", value="GTR", placeholder="Ingresa tu usuario")
            password_in = st.text_input("🔑 Contraseña:", type="password", placeholder="Ingresa tu contraseña")
            btn_entrar = st.form_submit_button("🚀 Ingresar a la Consola", width="stretch")

            if btn_entrar:
                u_clean = str(usuario_in).strip()
                p_clean = str(password_in).strip()

                # 1. PASE MAESTRO DIRECTO PARA GTR / ADMIN
                if u_clean.upper() in ["GTR", "ADMIN"] and p_clean in ["Aguas2026gtr", "aguas2026gtr", "GTR2026", "admin123", "1234"]:
                    try:
                        p_hash = hashlib.sha256(p_clean.encode("utf-8")).hexdigest()
                        con.execute("UPDATE usuarios_wfm SET password_hash = ?, estado = 'ACTIVO' WHERE UPPER(username) = 'GTR'", [p_hash])
                    except Exception:
                        pass

                    st.session_state["autenticado"] = True
                    st.session_state["usuario_actual"] = "GTR"
                    st.session_state["nombre_usuario_actual"] = "Administrador Maestro GTR"
                    st.session_state["rol_actual"] = "Jefe Control Operativo WFM (ADMIN)"
                    st.session_state["permiso_wfm"] = "ADMIN"
                    st.session_state["es_admin_wfm"] = True
                    st.rerun()
                else:
                    # 2. VERIFICACIÓN NORMAL PARA OTROS USUARIOS CREADOS EN LA TABLA
                    datos_user, msg = modulo_usuarios.verificar_credenciales(con, u_clean, p_clean)
                    if datos_user:
                        st.session_state["autenticado"] = True
                        st.session_state["usuario_actual"] = datos_user["username"]
                        st.session_state["nombre_usuario_actual"] = datos_user["nombre_completo"]
                        st.session_state["rol_actual"] = f"{datos_user['cargo']} ({datos_user['rol']})"
                        st.session_state["permiso_wfm"] = datos_user["rol"]
                        st.rerun()
                    else:
                        st.error(msg)