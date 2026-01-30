import streamlit as st
import pandas as pd
import os
import io
import zipfile
import shutil
from datetime import datetime
from sqlalchemy import text
from audio_recorder_streamlit import audio_recorder

# ---- 1. CONSTANTS & SYSTEM SETUP ----
DB_FILE = "ride_db.db"
UPLOAD_DIR = "task_assets"

if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# Initialize Connection
conn = st.connection("ride_db", type="sql")

def init_db():
    """Initializes the database schema and default admin."""
    with conn.session as session:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                task_name TEXT, location TEXT, task_status TEXT,
                task_desc_text TEXT, description_file TEXT,
                before_photo TEXT, after_photo TEXT,
                technician TEXT, rating INTEGER DEFAULT 0, 
                feedback TEXT DEFAULT '', 
                user_comment TEXT DEFAULT '',
                admin_comment TEXT DEFAULT '',
                start_time TEXT, end_time TEXT
            );
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY, password TEXT, role TEXT
            );
        """))
        # Check for default admin
        res = session.execute(text("SELECT COUNT(*) FROM users")).fetchone()
        if res[0] == 0:
            session.execute(text("INSERT INTO users VALUES ('admin', 'admin789', 'admin')"))
        session.commit()

# Run initialization
init_db()

# ---- 2. AUTHENTICATION ----
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

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

# ---- 3. DATABASE HELPERS ----
def update_task_field(task_id, field, value):
    with conn.session as session:
        session.execute(text(f"UPDATE tasks SET {field}=:v WHERE id=:id"), {"v": value, "id": task_id})
        session.commit()

def save_files(uploaded_files, prefix="img"):
    filenames = []
    if uploaded_files:
        for file in uploaded_files:
            fname = f"{prefix}_{datetime.now().strftime('%H%M%S')}_{file.name.replace(',', '_')}"
            with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
                f.write(file.getbuffer())
            filenames.append(fname)
    return ",".join(filenames) if filenames else None

# ---- 4. SIDEBAR: ADMIN TOOLS & EXPORTS ----
st.sidebar.title(f"👤 {st.session_state.username}")
if st.sidebar.button("Log Out"):
    for key in list(st.session_state.keys()): del st.session_state[key]
    st.rerun()

if st.session_state.user_role == "admin":
    st.sidebar.markdown("---")
    
    # SYSTEM EXPORT
    if st.sidebar.button("📥 Export All (ZIP + Excel)"):
        df = conn.query("SELECT * FROM tasks", ttl=0)
        if not df.empty:
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
                df.to_excel(writer, sheet_name='Main_Log', index=False)
            
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                zf.writestr("Maintenance_Report.xlsx", excel_buffer.getvalue())
                for root, _, files in os.walk(UPLOAD_DIR):
                    for file in files:
                        zf.write(os.path.join(root, file), os.path.join(UPLOAD_DIR, file))
            st.sidebar.download_button("💾 Download ZIP", zip_buffer.getvalue(), "Full_System_Backup.zip")

    # USER MANAGEMENT
    with st.sidebar.expander("👥 User Management"):
        with st.form("new_user_form", clear_on_submit=True):
            nu = st.text_input("New Username")
            np = st.text_input("New Password")
            nr = st.selectbox("Role", ["tech", "admin"])
            if st.form_submit_button("Create User"):
                with conn.session as session:
                    session.execute(text("INSERT INTO users VALUES (:u, :p, :r)"), {"u":nu, "p":np, "r":nr})
                    session.commit()
                st.rerun()
        
        st.write("**Current Users:**")
        all_u = conn.query("SELECT username, role FROM users", ttl=0)
        for _, urow in all_u.iterrows():
            c1, c2 = st.columns([3, 1])
            c1.write(f"{urow['username']} ({urow['role']})")
            if urow['username'] != 'admin' and c2.button("🗑️", key=f"u_{urow['username']}"):
                with conn.session as session:
                    session.execute(text("DELETE FROM users WHERE username=:u"), {"u":urow['username']})
                    session.commit()
                st.rerun()

    # EMERGENCY WIPE
    with st.sidebar.expander("🚨 Danger Zone"):
        st.error("System Wipe")
        confirm = st.text_input("Type 'DELETE' to confirm wipe")
        if st.button("🔥 DELETE DATABASE FILE", type="primary"):
            if confirm == "DELETE":
                st.cache_resource.clear()
                if os.path.exists(DB_FILE): os.remove(DB_FILE)
                if os.path.exists(UPLOAD_DIR): shutil.rmtree(UPLOAD_DIR)
                st.success("Wipe complete. Restarting...")
                st.rerun()

# ---- 5. UI: LOG NEW TASK ----
st.title("👨‍🔧 Maintenance Portal")
with st.expander("➕ Log New Task Entry", expanded=True):
    with st.form("task_entry", clear_on_submit=True):
        f1, f2 = st.columns(2)
        n = f1.text_input("Project Name")
        l = f2.text_input("📍 Location")
        
        f3, f4, f5 = st.columns(3)
        s = f3.selectbox("Status", ["🟡 In Progress", "🟠 Awaiting Parts", "🟢 Completed"])
        st_time = f4.text_input("Start Time", value=datetime.now().strftime("%Y-%m-%d %H:%M"))
        en_time = f5.text_input("End Time (Optional)")
        
        desc = st.text_area("Task Description")
        u_comm = st.text_area("Your Notes (Comment)")
        
        img_b = st.file_uploader("Before Photos", accept_multiple_files=True)
        img_a = st.file_uploader("After Photos", accept_multiple_files=True)
        
        submit = st.form_submit_button("Submit Record")

    st.write("🎙️ Audio Record")
    audio = audio_recorder(text="", icon_size="2x")

    if submit and n:
        aud_f = None
        if audio:
            aud_f = f"aud_{datetime.now().strftime('%H%M%S')}.wav"
            with open(os.path.join(UPLOAD_DIR, aud_f), "wb") as f: f.write(audio)
        
        b_names = save_files(img_b, "before")
        a_names = save_files(img_a, "after")
        
        with conn.session as session:
            session.execute(text("""
                INSERT INTO tasks (task_name, location, task_status, task_desc_text, description_file, 
                before_photo, after_photo, technician, user_comment, start_time, end_time) 
                VALUES (:n, :l, :s, :d, :df, :bp, :ap, :t, :uc, :st, :et)"""),
                {"n": n, "l": l, "s": s, "d": desc, "df": aud_f, "bp": b_names, "ap": a_names, 
                 "t": st.session_state.username, "uc": u_comm, "st": st_time, "et": en_time})
            session.commit()
        st.rerun()

# ---- 6. UI: HISTORY & EDITING ----
st.write("---")
st.header("📋 Task History")

try:
    df_tasks = conn.query("SELECT * FROM tasks ORDER BY id DESC", ttl=0)
    for _, row in df_tasks.iterrows():
        is_adm = st.session_state.user_role == "admin"
        can_edit = is_adm or (st.session_state.username == row['technician'])
        
        with st.container(border=True):
            h1, h2 = st.columns([5, 1])
            h1.subheader(f"{row['task_status']} | {row['task_name']}")
            if is_adm and h2.button("🗑️", key=f"t_{row['id']}"):
                with conn.session as session:
                    session.execute(text("DELETE FROM tasks WHERE id=:id"), {"id":row['id']})
                    session.commit()
                st.rerun()
            
            st.caption(f"👤 {row['technician']} | 📅 {row['start_time']} ➔ {row['end_time']}")
            
            # Photos Display with Deletion logic
            for label, col_key in [("Before", "before_photo"), ("After", "after_photo")]:
                if row[col_key]:
                    st.write(f"**{label} Photos:**")
                    imgs = row[col_key].split(",")
                    p_cols = st.columns(5)
                    for i, img in enumerate(imgs):
                        with p_cols[i % 5]:
                            st.image(os.path.join(UPLOAD_DIR, img))
                            if can_edit and st.button("Delete", key=f"p_{row['id']}_{col_key}_{i}"):
                                imgs.pop(i)
                                update_task_field(row['id'], col_key, ",".join(imgs) if imgs else None)
                                st.rerun()

            # Comment Sections
            st.info(f"**Tech Comment:** {row['user_comment']}")
            if can_edit:
                with st.popover("Edit My Comment"):
                    new_u_c = st.text_area("Edit", value=row['user_comment'], key=f"eu_{row['id']}")
                    if st.button("Update", key=f"ub_{row['id']}"):
                        update_task_field(row['id'], "user_comment", new_u_c)
                        st.rerun()
            
            st.warning(f"**Admin Feedback:** {row['admin_comment']}")
            if is_adm:
                with st.popover("Edit Admin Feedback"):
                    new_a_c = st.text_area("Feedback", value=row['admin_comment'], key=f"ea_{row['id']}")
                    if st.button("Save Feedback", key=f"ab_{row['id']}"):
                        update_task_field(row['id'], "admin_comment", new_a_c)
                        st.rerun()

            if row['description_file']:
                st.audio(os.path.join(UPLOAD_DIR, row['description_file']))

except Exception:
    st.info("No records found. If you just performed a wipe, log a new task to begin.")
