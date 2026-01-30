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

# Create the media directory if it doesn't exist
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# SQLite Connection
conn = st.connection("ride_db", type="sql")

def init_db():
    """Initializes tables and ensures default admin persistence."""
    with conn.session as session:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                task_name TEXT, location TEXT, task_status TEXT,
                task_desc_text TEXT, description_file TEXT,
                before_photo TEXT, after_photo TEXT,
                technician TEXT, rating INTEGER DEFAULT 0, 
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
        # Check for initial admin
        res = session.execute(text("SELECT COUNT(*) FROM users")).fetchone()
        if res[0] == 0:
            session.execute(text("INSERT INTO users (username, password, role) VALUES ('admin', 'admin789', 'admin')"))
        session.commit()

init_db()

# ---- 2. STORAGE METRICS ----
def get_size_format(b, factor=1024, suffix="B"):
    for unit in ["", "K", "M", "G", "T"]:
        if b < factor: return f"{b:.2f}{unit}{suffix}"
        b /= factor

def get_dir_size(path='.'):
    total = 0
    if not os.path.exists(path): return 0
    with os.scandir(path) as it:
        for entry in it:
            if entry.is_file(): total += entry.stat().st_size
            elif entry.is_dir(): total += get_dir_size(entry.path)
    return total

# ---- 3. AUTHENTICATION ----
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("🔐 Professional Portal Login")
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
                st.error("Invalid credentials.")
    st.stop()

# ---- 4. FILE & DATABASE HELPERS ----
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

# ---- 5. SIDEBAR: ADMIN TOOLS & STORAGE MONITOR ----
st.sidebar.title(f"👤 {st.session_state.username}")
if st.sidebar.button("Log Out"):
    for key in list(st.session_state.keys()): del st.session_state[key]
    st.rerun()

if st.session_state.user_role == "admin":
    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 System Storage")
    
    db_size = os.path.getsize(DB_FILE) if os.path.exists(DB_FILE) else 0
    assets_size = get_dir_size(UPLOAD_DIR)
    
    col_s1, col_s2 = st.sidebar.columns(2)
    col_s1.metric("Database", get_size_format(db_size))
    col_s2.metric("Media", get_size_format(assets_size))
    
    # EXPORT ZIP
    if st.sidebar.button("📥 Export Project ZIP"):
        df = conn.query("SELECT * FROM tasks", ttl=0)
        if not df.empty:
            excel_buffer = io.BytesIO()
            df_export = df.copy()
            # Clean symbols for Excel
            df_export['task_status'] = df_export['task_status'].str.replace('🟡 ', '').str.replace('🟠 ', '').str.replace('🟢 ', '')
            with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
                df_export.to_excel(writer, sheet_name='Report', index=False)
                workbook, worksheet = writer.book, writer.sheets['Report']
                link_fmt = workbook.add_format({'color': 'blue', 'underline': 1})
                for i, row in df_export.iterrows():
                    for col_idx, col_name in [(6, 'before_photo'), (7, 'after_photo')]:
                        if row[col_name]:
                            first_img = row[col_name].split(',')[0]
                            worksheet.write_url(i + 1, col_idx, f"external:task_assets/{first_img}", link_fmt, "View Image")

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                zf.writestr("Maintenance_Log.xlsx", excel_buffer.getvalue())
                if os.path.exists(UPLOAD_DIR):
                    for root, _, files in os.walk(UPLOAD_DIR):
                        for file in files:
                            zf.write(os.path.join(root, file), os.path.join(UPLOAD_DIR, file))
            st.sidebar.download_button("💾 Download ZIP", zip_buffer.getvalue(), "Full_System_Backup.zip")

    # USER MANAGEMENT (PERSISTENT)
    with st.sidebar.expander("👥 User Management"):
        st.write("**Add User Account**")
        n_u = st.text_input("New Username", key="nu")
        n_p = st.text_input("New Password", key="np")
        n_r = st.selectbox("Role", ["tech", "admin"], key="nr")
        if st.button("➕ Create Account", use_container_width=True):
            if n_u and n_p:
                with conn.session as session:
                    session.execute(text("INSERT INTO users (username, password, role) VALUES (:u, :p, :r)"), {"u": n_u, "p": n_p, "r": n_r})
                    session.commit()
                st.success(f"Added {n_u}")
                st.rerun()

        st.divider()
        st.write("**Modify Users**")
        all_u = conn.query("SELECT * FROM users", ttl=0)
        for _, urow in all_u.iterrows():
            with st.container(border=True):
                eu = st.text_input("User", value=urow['username'], key=f"eu_{urow['username']}")
                ep = st.text_input("Pass", value=urow['password'], key=f"ep_{urow['username']}")
                c1, c2 = st.columns(2)
                if c1.button("Save", key=f"s_{urow['username']}", use_container_width=True):
                    with conn.session as session:
                        session.execute(text("UPDATE users SET username=:nu, password=:np WHERE username=:ou"), {"nu": eu, "np": ep, "ou": urow['username']})
                        session.commit()
                    st.rerun()
                if urow['username'] != 'admin' and c2.button("Del", key=f"d_{urow['username']}", use_container_width=True):
                    with conn.session as session:
                        session.execute(text("DELETE FROM users WHERE username=:u"), {"u": urow['username']})
                        session.commit()
                    st.rerun()

    # DANGER ZONE: DATA WIPE
    with st.sidebar.expander("🚨 Emergency Recovery"):
        st.warning("Deletes tasks and photos only. Accounts remain.")
        confirm = st.text_input("Type 'WIPE' to confirm")
        if st.button("🗑️ CLEAR ALL TASK DATA", type="primary"):
            if confirm == "WIPE":
                with conn.session as session:
                    session.execute(text("DELETE FROM tasks"))
                    session.execute(text("DELETE FROM sqlite_sequence WHERE name='tasks'"))
                    session.commit()
                if os.path.exists(UPLOAD_DIR):
                    shutil.rmtree(UPLOAD_DIR)
                    os.makedirs(UPLOAD_DIR)
                st.rerun()

# ---- 6. UI: LOG MAINTENANCE ----
st.title("👨‍🔧 Maintenance Management")
with st.expander("➕ Log New Maintenance Task", expanded=True):
    with st.form("task_submission"):
        r1_1, r1_2 = st.columns(2)
        t_title, t_loc = r1_1.text_input("Project Name"), r1_2.text_input("📍 Location")
        
        r2_1, r2_2, r2_3 = st.columns(3)
        t_stat = r2_1.selectbox("Status", ["In Progress", "Awaiting Parts", "Completed"])
        sd, st_t = r2_2.date_input("Start Date"), r2_2.time_input("Start Time")
        ed, et_t = r2_3.date_input("End Date"), r2_3.time_input("End Time")
        
        t_desc, t_note = st.text_area("Task Description"), st.text_area("Tech Comments")
        up_b = st.file_uploader("Before Photos", accept_multiple_files=True)
        up_a = st.file_uploader("After Photos", accept_multiple_files=True)
        
        if st.form_submit_button("🚀 Submit Final Entry", use_container_width=True):
            status_map = {"In Progress": "🟡 In Progress", "Awaiting Parts": "🟠 Awaiting Parts", "Completed": "🟢 Completed"}
            b_names, a_names = save_files(up_b, "before"), save_files(up_a, "after")
            with conn.session as session:
                session.execute(text("""INSERT INTO tasks (task_name, location, task_status, task_desc_text, 
                    before_photo, after_photo, technician, user_comment, start_time, end_time) 
                    VALUES (:n, :l, :s, :d, :bp, :ap, :t, :uc, :st, :et)"""),
                    {"n": t_title, "l": t_loc, "s": status_map[t_stat], "d": t_desc, "bp": b_names, "ap": a_names, 
                     "t": st.session_state.username, "uc": t_note, "st": f"{sd} {st_t}", "et": f"{ed} {et_t}"})
                session.commit()
            st.rerun()

# ---- 7. HISTORY & REVIEWS ----
st.write("---")
st.header("📋 Task History")

df_tasks = conn.query("SELECT * FROM tasks ORDER BY id DESC", ttl=0)

for _, row in df_tasks.iterrows():
    is_admin = st.session_state.user_role == "admin"
    can_edit = is_admin or (st.session_state.username == row['technician'])
    
    with st.container(border=True):
        c_h1, c_h2 = st.columns([5, 1])
        c_h1.subheader(f"{row['task_status']} | {row['task_name']}")
        if is_admin and c_h2.button("🗑️", key=f"del_rec_{row['id']}"):
            with conn.session as session:
                session.execute(text("DELETE FROM tasks WHERE id=:id"), {"id": row['id']})
                session.commit()
            st.rerun()

        st.caption(f"👤 {row['technician']} | 🕒 {row['start_time']} to {row['end_time']}")
        
        # Display/Delete Photos
        for label, col in [("Before", "before_photo"), ("After", "after_photo")]:
            if row[col]:
                st.write(f"**{label} Documentation:**")
                imgs = row[col].split(",")
                p_cols = st.columns(5)
                for i, img in enumerate(imgs):
                    with p_cols[i % 5]:
                        st.image(os.path.join(UPLOAD_DIR, img))
                        if can_edit and st.button("Del", key=f"di_{row['id']}_{col}_{i}"):
                            imgs.pop(i)
                            update_task_field(row['id'], col, ",".join(imgs) if imgs else None)
                            st.rerun()

        # Admin Feedback
        st.divider()
        st.write(f"⭐ **Quality Score:** {row['rating']}/10 | 📝 **Review:** {row['admin_comment']}")
        
        if is_admin:
            with st.popover("📝 Leave Admin Review"):
                nr = st.select_slider("Score", options=list(range(11)), value=int(row['rating']))
                ac = st.text_area("Admin Feedback", value=row['admin_comment'])
                if st.button("Save", key=f"sr_{row['id']}"):
                    with conn.session as session:
                        session.execute(text("UPDATE tasks SET rating=:r, admin_comment=:c WHERE id=:id"), {"r": nr, "c": ac, "id": row['id']})
                        session.commit()
                    st.rerun()

        # ADVANCED EDIT: ADD BEFORE/AFTER PHOTOS
        if can_edit:
            with st.expander("🛠️ Advanced Edit (Add Photos & Info)"):
                with st.form(f"adv_edit_{row['id']}"):
                    ed_n, ed_l = st.text_input("Project Name", value=row['task_name']), st.text_input("Location", value=row['location'])
                    ed_s = st.selectbox("Status Update", ["🟡 In Progress", "🟠 Awaiting Parts", "🟢 Completed"])
                    
                    st.write("**Upload Extra Photos:**")
                    col_b, col_a = st.columns(2)
                    add_b = col_b.file_uploader("➕ Add to Before", accept_multiple_files=True, key=f"ab_{row['id']}")
                    add_a = col_a.file_uploader("➕ Add to After", accept_multiple_files=True, key=f"aa_{row['id']}")
                    
                    if st.form_submit_button("Update Task Details"):
                        new_b_names = save_files(add_b, f"extra_b_{row['id']}")
                        new_a_names = save_files(add_a, f"extra_a_{row['id']}")
                        
                        # Merge existing with new strings
                        final_b = (row['before_photo'] + "," + new_b_names) if row['before_photo'] and new_b_names else (new_b_names or row['before_photo'])
                        final_a = (row['after_photo'] + "," + new_a_names) if row['after_photo'] and new_a_names else (new_a_names or row['after_photo'])
                        
                        with conn.session as session:
                            session.execute(text("""UPDATE tasks SET task_name=:n, location=:l, task_status=:s, 
                                before_photo=:bp, after_photo=:ap WHERE id=:id"""),
                                {"n": ed_n, "l": ed_l, "s": ed_s, "bp": final_b, "ap": final_a, "id": row['id']})
                            session.commit()
                        st.rerun()
