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

conn = st.connection("ride_db", type="sql")

with conn.session as session:
    # Task Table - Expanded Schema
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
    # User Table
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

# ---- 3. HELPERS ----
def save_files(uploaded_files, prefix="img"):
    filenames = []
    if uploaded_files:
        for file in uploaded_files:
            fname = f"{prefix}_{datetime.now().strftime('%H%M%S')}_{file.name.replace(',', '_')}"
            with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
                f.write(file.getbuffer())
            filenames.append(fname)
    return ",".join(filenames) if filenames else None

def update_task_field(task_id, field, value):
    with conn.session as session:
        session.execute(text(f"UPDATE tasks SET {field}=:v WHERE id=:id"), {"v": value, "id": task_id})
        session.commit()

# ---- 4. SIDEBAR (User Management & Enhanced Export) ----
st.sidebar.title(f"👤 {st.session_state.username}")
if st.sidebar.button("Log Out"):
    for key in list(st.session_state.keys()): del st.session_state[key]
    st.rerun()

if st.session_state.user_role == "admin":
    st.sidebar.markdown("---")
    with st.sidebar.expander("👥 User Management", expanded=False):
        # Create User
        with st.form("add_user", clear_on_submit=True):
            st.subheader("Add New User")
            new_u = st.text_input("Username")
            new_p = st.text_input("Password")
            new_r = st.selectbox("Role", ["tech", "admin"])
            if st.form_submit_button("Add User"):
                with conn.session as session:
                    session.execute(text("INSERT INTO users VALUES (:u, :p, :r)"), {"u":new_u, "p":new_p, "r":new_r})
                    session.commit()
                st.rerun()
        
        # Delete User UI
        st.markdown("---")
        st.subheader("Existing Users")
        all_users = conn.query("SELECT username, role FROM users", ttl=0)
        for _, u_row in all_users.iterrows():
            col_u, col_d = st.columns([3, 1])
            col_u.write(f"**{u_row['username']}** ({u_row['role']})")
            if u_row['username'] != 'admin':
                if col_d.button("🗑️", key=f"del_u_{u_row['username']}"):
                    with conn.session as session:
                        session.execute(text("DELETE FROM users WHERE username=:u"), {"u":u_row['username']})
                        session.commit()
                    st.rerun()

    # --- ENHANCED EXCEL & ZIP EXPORT ---
    if st.sidebar.button("📥 Export Comprehensive Report (ZIP)"):
        df = conn.query("SELECT * FROM tasks", ttl=0)
        if not df.empty:
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
                # Include all new columns (start/end time, comments)
                df.to_excel(writer, sheet_name='Detailed_Log', index=False)
                workbook, worksheet = writer.book, writer.sheets['Detailed_Log']
                header_fmt = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1})
                link_fmt = workbook.add_format({'color': 'blue', 'underline': 1})
                
                # Column widths for readability
                worksheet.set_column('A:Q', 15)
                
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                zf.writestr("Maintenance_Master_Report.xlsx", excel_buffer.getvalue())
                if os.path.exists(UPLOAD_DIR):
                    for root, _, files in os.walk(UPLOAD_DIR):
                        for file in files:
                            zf.write(os.path.join(root, file), os.path.join(UPLOAD_DIR, file))
            st.sidebar.download_button("💾 Download ZIP Package", zip_buffer.getvalue(), f"Full_Export_{datetime.now().strftime('%Y%m%d')}.zip")

# ---- 5. UI: LOGGING NEW TASK ----
st.title("👨‍🔧 Maintenance Portal")
with st.expander("➕ Create New Maintenance Record", expanded=True):
    with st.form("new_task_form"):
        c1, c2 = st.columns(2)
        t_name = c1.text_input("Task/Project Name")
        t_loc = c2.text_input("📍 Work Location")
        
        c3, c4, c5 = st.columns(3)
        t_status = c3.selectbox("Status", ["🟡 In Progress", "🟠 Awaiting Parts", "🟢 Completed"])
        t_start = c4.text_input("Start (Date/Time)", value=datetime.now().strftime("%Y-%m-%d %H:%M"))
        t_end = c5.text_input("End (Date/Time)")
        
        t_desc = st.text_area("General Description")
        t_u_comm = st.text_area("Technician Notes/Comments")
        
        st.markdown("---")
        col_fb, col_fa = st.columns(2)
        b_imgs = col_fb.file_uploader("Upload Before Photos", type=['jpg','png'], accept_multiple_files=True)
        a_imgs = col_fa.file_uploader("Upload After Photos", type=['jpg','png'], accept_multiple_files=True)
        
        submitted = st.form_submit_button("🚀 Submit Final Record")

    st.write("🎙️ **Optional Audio Memo**")
    audio_bytes = audio_recorder(text="", icon_size="2x")

    if submitted:
        if t_name:
            aud_name = f"aud_{datetime.now().strftime('%H%M%S')}.wav" if audio_bytes else None
            if aud_name:
                with open(os.path.join(UPLOAD_DIR, aud_name), "wb") as f: f.write(audio_bytes)
            
            b_names = save_files(b_imgs, "before")
            a_names = save_files(a_imgs, "after")
            
            with conn.session as session:
                session.execute(text("""
                    INSERT INTO tasks (task_name, location, task_status, task_desc_text, description_file, 
                    before_photo, after_photo, technician, user_comment, start_time, end_time) 
                    VALUES (:n, :l, :s, :d, :df, :bp, :ap, :t, :uc, :st, :et)"""),
                    {"n": t_name, "l": t_loc, "s": t_status, "d": t_desc, "df": aud_name, 
                     "bp": b_names, "ap": a_names, "t": st.session_state.username, 
                     "uc": t_u_comm, "st": t_start, "et": t_end})
                session.commit()
            st.success("Record Saved!")
            st.rerun()

# ---- 6. UI: SMART HISTORY & DYNAMIC EDITING ----
st.header("📋 Task Management History")
df_tasks = conn.query("SELECT * FROM tasks ORDER BY id DESC", ttl=0)

for _, row in df_tasks.iterrows():
    # Role-Based Permissions
    is_admin = st.session_state.user_role == "admin"
    is_owner = st.session_state.username == row['technician']
    can_edit = is_admin or is_owner
    
    with st.container(border=True):
        col_title, col_del = st.columns([5, 1])
        col_title.subheader(f"{row['task_status']} | {row['task_name']}")
        
        if is_admin:
            if col_del.button("🗑️ Delete Task", key=f"main_del_{row['id']}", type="primary"):
                with conn.session as session:
                    session.execute(text("DELETE FROM tasks WHERE id=:id"), {"id": row['id']})
                    session.commit()
                st.rerun()

        st.caption(f"👤 Tech: {row['technician']} | 📅 {row['start_time']} ➔ {row['end_time']}")
        
        # --- Image Management Section ---
        for label, col_key in [("Before", "before_photo"), ("After", "after_photo")]:
            if row[col_key]:
                st.write(f"**{label} Photos:**")
                img_list = row[col_key].split(",")
                cols = st.columns(5)
                for i, img_file in enumerate(img_list):
                    with cols[i % 5]:
                        st.image(os.path.join(UPLOAD_DIR, img_file), use_container_width=True)
                        if can_edit:
                            if st.button("Delete", key=f"img_del_{row['id']}_{col_key}_{i}"):
                                img_list.pop(i)
                                update_task_field(row['id'], col_key, ",".join(img_list) if img_list else None)
                                st.rerun()
        
        # Add new photos to existing task
        if can_edit:
            with st.expander("➕ Add More Photos"):
                new_up = st.file_uploader("Select files", type=['jpg','png'], accept_multiple_files=True, key=f"new_img_{row['id']}")
                target_col = st.radio("Add to:", ["Before", "After"], key=f"target_{row['id']}")
                if st.button("Upload to this Record", key=f"up_btn_{row['id']}"):
                    col_to_up = "before_photo" if target_col == "Before" else "after_photo"
                    new_names = save_files(new_up, "added")
                    existing = row[col_to_up] if row[col_to_up] else ""
                    combined = f"{existing},{new_names}" if existing else new_names
                    update_task_field(row['id'], col_to_up, combined)
                    st.rerun()

        # --- Comments & Feedback Section ---
        st.divider()
        c_tech, c_admin = st.columns(2)
        
        with c_tech:
            st.info(f"**Technician Notes:**\n\n{row['user_comment']}")
            if can_edit:
                with st.popover("📝 Edit Tech Notes"):
                    new_u_text = st.text_area("Update Comment", value=row['user_comment'], key=f"u_txt_{row['id']}")
                    if st.button("Save Changes", key=f"u_btn_{row['id']}"):
                        update_task_field(row['id'], "user_comment", new_u_text)
                        st.rerun()
        
        with c_admin:
            st.warning(f"**Admin Feedback:**\n\n{row['admin_comment']}")
            if is_admin:
                with st.popover("✍️ Edit Admin Feedback"):
                    new_a_text = st.text_area("Update Feedback", value=row['admin_comment'], key=f"a_txt_{row['id']}")
                    if st.button("Save Feedback", key=f"a_btn_{row['id']}"):
                        update_task_field(row['id'], "admin_comment", new_a_text)
                        st.rerun()

        # Audio Playback
        if row['description_file']:
            st.audio(os.path.join(UPLOAD_DIR, row['description_file']))
