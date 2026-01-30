import streamlit as st
import pandas as pd
import os
import io
import zipfile
import shutil
from datetime import datetime
from sqlalchemy import text
from audio_recorder_streamlit import audio_recorder

# ---- 1. SETUP & DB ----
UPLOAD_DIR = "task_assets"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# Connection to the SQLite database
conn = st.connection("ride_db", type="sql")

with conn.session as session:
    # Create Tables
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            task_name TEXT, location TEXT, task_status TEXT,
            task_desc_text TEXT, description_file TEXT,
            before_photo TEXT, after_photo TEXT,
            technician TEXT, rating INTEGER DEFAULT 0, feedback TEXT DEFAULT ''
        );
    """))
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY, password TEXT, role TEXT
        );
    """))
    # Default Admin
    res = session.execute(text("SELECT COUNT(*) FROM users")).fetchone()
    if res[0] == 0:
        session.execute(text("INSERT INTO users VALUES ('admin', 'admin789', 'admin')"))
    session.commit()

# ---- 2. AUTHENTICATION & INITIALIZATION ----
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'username' not in st.session_state:
    st.session_state.username = None

if not st.session_state.logged_in:
    st.title("🔐 Technician Portal Login")
    with st.container(border=True):
        u_input = st.text_input("Username")
        p_input = st.text_input("Password", type="password")
        if st.button("Login", use_container_width=True):
            user_db = conn.query("SELECT * FROM users WHERE username=:u AND password=:p", 
                                 params={"u": u_input, "p": p_input}, ttl=0)
            if not user_db.empty:
                st.session_state.logged_in = True
                st.session_state.username = u_input
                st.session_state.user_role = user_db.iloc[0]['role']
                st.rerun()
            else:
                st.error("Invalid credentials")
    st.stop()

# ---- 3. FILE SAVING HELPER ----
def save_files(uploaded_files, prefix="img"):
    filenames = []
    if uploaded_files:
        for file in uploaded_files:
            fname = f"{prefix}_{datetime.now().strftime('%H%M%S')}_{file.name.replace(',', '_')}"
            with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
                f.write(file.getbuffer())
            filenames.append(fname)
    return ",".join(filenames) if filenames else None

# ---- 4. SIDEBAR ----
st.sidebar.title(f"👤 {st.session_state.username}")
if st.sidebar.button("Log Out"):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

if st.session_state.user_role == "admin":
    st.sidebar.markdown("---")
    with st.sidebar.expander("👥 User Management"):
        with st.form("add_user", clear_on_submit=True):
            new_u = st.text_input("Username")
            new_p = st.text_input("Password")
            new_r = st.selectbox("Role", ["tech", "admin"])
            if st.form_submit_button("Save New User"):
                with conn.session as session:
                    session.execute(text("INSERT INTO users VALUES (:u, :p, :r)"), {"u":new_u, "p":new_p, "r":new_r})
                    session.commit()
                st.rerun()
    
    # --- ZIP & EXCEL EXPORT ---
    if st.sidebar.button("📥 Export Full Package (ZIP)"):
        df = conn.query("SELECT * FROM tasks", ttl=0)
        if not df.empty:
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
                export_df = df.drop(columns=['before_photo', 'after_photo', 'description_file'])
                export_df.to_excel(writer, sheet_name='Report', index=False)
                workbook, worksheet = writer.book, writer.sheets['Report']
                link_fmt = workbook.add_format({'color': 'blue', 'underline': 1})
                
                for i, row in df.iterrows():
                    if row['description_file']:
                        worksheet.write_url(i + 1, 8, f"external:task_assets/{row['description_file']}", link_fmt, "Play Audio")
                    if row['before_photo']:
                        for idx, f in enumerate(row['before_photo'].split(",")[:5]):
                            worksheet.write_url(i + 1, 9 + idx, f"external:task_assets/{f}", link_fmt, "Photo")
                    if row['after_photo']:
                        for idx, f in enumerate(row['after_photo'].split(",")[:5]):
                            worksheet.write_url(i + 1, 14 + idx, f"external:task_assets/{f}", link_fmt, "Photo")

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                zf.writestr("Maintenance_Report.xlsx", excel_buffer.getvalue())
                if os.path.exists(UPLOAD_DIR):
                    for root, _, files in os.walk(UPLOAD_DIR):
                        for file in files:
                            zf.write(os.path.join(root, file), os.path.join(UPLOAD_DIR, file))

            st.sidebar.download_button("💾 Download ZIP", zip_buffer.getvalue(), "Report_Package.zip", "application/zip")

    if st.sidebar.button("⚠️ Clear All Task History", type="primary"):
        with conn.session as session:
            session.execute(text("DELETE FROM tasks"))
            session.commit()
        if os.path.exists(UPLOAD_DIR):
            shutil.rmtree(UPLOAD_DIR)
            os.makedirs(UPLOAD_DIR)
        st.rerun()

# ---- 5. UI: SUBMISSION ----
st.title("👨‍🔧 Maintenance Portal")
with st.expander("➕ Log New Maintenance Task", expanded=True):
    col_n, col_l, col_s = st.columns([1.5, 1.5, 1])
    with col_n: t_name = st.text_input("Project Name")
    with col_l: t_loc = st.text_input("📍 Work Location")
    with col_s: t_status = st.selectbox("Status", ["🟡 In Progress", "🟠 Awaiting Parts", "🟢 Completed"])
    
    t_desc = st.text_area("Task Details")
    c_aud, c_b, c_a = st.columns(3)
    with c_aud:
        st.write("🎙️ Audio")
        audio_bytes = audio_recorder(text="", icon_size="3x")
    with c_b:
        b_imgs = st.file_uploader("Before Photos", type=['jpg','png'], accept_multiple_files=True)
    with c_a:
        a_imgs = st.file_uploader("After Photos", type=['jpg','png'], accept_multiple_files=True)

    if st.button("🚀 Submit Final Report", use_container_width=True):
        if t_name:
            aud_name = None
            if audio_bytes:
                aud_name = f"aud_{datetime.now().strftime('%H%M%S')}.wav"
                with open(os.path.join(UPLOAD_DIR, aud_name), "wb") as f: f.write(audio_bytes)
            b_names = save_files(b_imgs, "before")
            a_names = save_files(a_imgs, "after")
            with conn.session as session:
                session.execute(text("INSERT INTO tasks (task_name, location, task_status, task_desc_text, description_file, before_photo, after_photo, technician) VALUES (:n, :l, :s, :d, :df, :bp, :ap, :t)"),
                                {"n": t_name, "l": t_loc, "s": t_status, "d": t_desc, "df": aud_name, "bp": b_names, "ap": a_names, "t": st.session_state.username})
                session.commit()
            st.rerun()

# ---- 6. UI: HISTORY ----
st.write("---")
st.header("📋 History")
df_tasks = conn.query("SELECT * FROM tasks ORDER BY id DESC", ttl=0)

for _, row in df_tasks.iterrows():
    with st.container(border=True):
        c_txt, c_btn = st.columns([4, 1])
        with c_txt:
            st.subheader(f"{row['task_status']} | {row['task_name']}")
            st.caption(f"👤 {row['technician']} | 📍 {row['location']}")
        
        if st.session_state.user_role == "admin":
            if c_btn.button("🗑️", key=f"del_{row['id']}"):
                with conn.session as session:
                    session.execute(text("DELETE FROM tasks WHERE id=:id"), {"id": row['id']})
                    session.commit()
                st.rerun()

        if row['task_desc_text']: st.info(row['task_desc_text'])
        if row['description_file']:
            aud_path = os.path.join(UPLOAD_DIR, row['description_file'])
            if os.path.exists(aud_path): st.audio(aud_path)
        
        col_b, col_a = st.columns(2)
        with col_b:
            if row['before_photo']: 
                for img in row['before_photo'].split(","):
                    path = os.path.join(UPLOAD_DIR, img)
                    if os.path.exists(path): st.image(path, width=150)
        with col_a:
            if row['after_photo']: 
                for img in row['after_photo'].split(","):
                    path = os.path.join(UPLOAD_DIR, img)
                    if os.path.exists(path): st.image(path, width=150)
