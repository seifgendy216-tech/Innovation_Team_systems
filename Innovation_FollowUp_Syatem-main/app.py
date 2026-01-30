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

conn = st.connection("ride_db", type="sql")

def init_db():
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
        res = session.execute(text("SELECT COUNT(*) FROM users")).fetchone()
        if res[0] == 0:
            session.execute(text("INSERT INTO users VALUES ('admin', 'admin789', 'admin')"))
        session.commit()

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
    
    if st.sidebar.button("📥 Export Comprehensive Report"):
        df = conn.query("SELECT * FROM tasks", ttl=0)
        if not df.empty:
            excel_buffer = io.BytesIO()
            df_export = df.copy()
            df_export['task_status'] = df_export['task_status'].str.replace('🟡 ', '').str.replace('🟠 ', '').str.replace('🟢 ', '')
            
            with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
                df_export.to_excel(writer, sheet_name='Report', index=False)
                workbook, worksheet = writer.book, writer.sheets['Report']
                link_fmt = workbook.add_format({'color': 'blue', 'underline': 1})
                
                # Excel Photo Hyperlinks
                for i, row in df_export.iterrows():
                    for col_idx, col_name in [(6, 'before_photo'), (7, 'after_photo')]:
                        if row[col_name]:
                            first_img = row[col_name].split(',')[0]
                            worksheet.write_url(i + 1, col_idx, f"external:task_assets/{first_img}", link_fmt, "View Image")

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                zf.writestr("Maintenance_Log.xlsx", excel_buffer.getvalue())
                for root, _, files in os.walk(UPLOAD_DIR):
                    for file in files:
                        zf.write(os.path.join(root, file), os.path.join(UPLOAD_DIR, file))
            st.sidebar.download_button("💾 Download ZIP Package", zip_buffer.getvalue(), "Project_Export.zip")

    with st.sidebar.expander("👥 User Management"):
        all_u = conn.query("SELECT * FROM users", ttl=0)
        for _, urow in all_u.iterrows():
            with st.container(border=True):
                new_uname = st.text_input("Name", value=urow['username'], key=f"un_{urow['username']}")
                new_pass = st.text_input("Pass", value=urow['password'], key=f"pw_{urow['username']}")
                if st.button("Save Credentials", key=f"sv_{urow['username']}"):
                    with conn.session as session:
                        session.execute(text("UPDATE users SET username=:nu, password=:np WHERE username=:ou"), 
                                        {"nu": new_uname, "np": new_pass, "ou": urow['username']})
                        session.commit()
                    st.rerun()

    with st.sidebar.expander("🚨 Danger Zone"):
        confirm = st.text_input("Type 'DELETE' to wipe system")
        if st.button("🔥 WIPE DATABASE", type="primary"):
            if confirm == "DELETE":
                st.cache_resource.clear()
                if os.path.exists(DB_FILE): os.remove(DB_FILE)
                if os.path.exists(UPLOAD_DIR): shutil.rmtree(UPLOAD_DIR)
                st.rerun()

# ---- 5. UI: LOG NEW TASK ----
st.title("👨‍🔧 Maintenance Portal")
with st.expander("➕ Create New Maintenance Entry", expanded=True):
    with st.form("new_task"):
        c1, c2 = st.columns(2)
        n, l = c1.text_input("Project Name"), c2.text_input("📍 Location")
        
        c3, c4, c5 = st.columns(3)
        s = c3.selectbox("Status", ["🟡 In Progress", "🟠 Awaiting Parts", "🟢 Completed"])
        sd, st_t = c4.date_input("Start Date"), c4.time_input("Start Time")
        ed, et_t = c5.date_input("End Date"), c5.time_input("End Time")
        
        desc, u_comm = st.text_area("Description"), st.text_area("Tech Notes")
        img_b = st.file_uploader("Before Photos", accept_multiple_files=True)
        img_a = st.file_uploader("After Photos", accept_multiple_files=True)
        
        if st.form_submit_button("Submit Record"):
            b_names = save_files(img_b, "before")
            a_names = save_files(img_a, "after")
            with conn.session as session:
                session.execute(text("""INSERT INTO tasks (task_name, location, task_status, task_desc_text, 
                    before_photo, after_photo, technician, user_comment, start_time, end_time) 
                    VALUES (:n, :l, :s, :d, :bp, :ap, :t, :uc, :st, :et)"""),
                    {"n": n, "l": l, "s": s, "d": desc, "bp": b_names, "ap": a_names, 
                     "t": st.session_state.username, "uc": u_comm, "st": f"{sd} {st_t}", "et": f"{ed} {et_t}"})
                session.commit()
            st.rerun()

# ---- 6. HISTORY & SMART EDITING ----
st.header("📋 Maintenance History")
df_tasks = conn.query("SELECT * FROM tasks ORDER BY id DESC", ttl=0)

for _, row in df_tasks.iterrows():
    is_adm = st.session_state.user_role == "admin"
    can_edit = is_adm or (st.session_state.username == row['technician'])
    
    with st.container(border=True):
        st.subheader(f"{row['task_status']} | {row['task_name']}")
        st.caption(f"👤 {row['technician']} | 📍 {row['location']} | 📅 {row['start_time']} to {row['end_time']}")
        
        # --- PHOTOS SECTION ---
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

        # --- SMART EDITING EXPANDER ---
        if can_edit:
            with st.expander("🛠️ Edit Task Details & Photos"):
                en = st.text_input("Name", value=row['task_name'], key=f"en_{row['id']}")
                el = st.text_input("Location", value=row['location'], key=f"el_{row['id']}")
                es = st.selectbox("Status", ["🟡 In Progress", "🟠 Awaiting Parts", "🟢 Completed"], 
                                  index=["🟡 In Progress", "🟠 Awaiting Parts", "🟢 Completed"].index(row['task_status']), key=f"es_{row['id']}")
                
                st.write("**Add More Photos:**")
                new_up_b = st.file_uploader("Add to Before", accept_multiple_files=True, key=f"ub_{row['id']}")
                new_up_a = st.file_uploader("Add to After", accept_multiple_files=True, key=f"ua_{row['id']}")

                if st.button("Update Task", key=f"ubtn_{row['id']}"):
                    added_b = save_files(new_up_b, "extra_b")
                    added_a = save_files(new_up_a, "extra_a")
                    
                    b_final = f"{row['before_photo']},{added_b}" if row['before_photo'] and added_b else (added_b or row['before_photo'])
                    a_final = f"{row['after_photo']},{added_a}" if row['after_photo'] and added_a else (added_a or row['after_photo'])
                    
                    with conn.session as session:
                        session.execute(text("""UPDATE tasks SET task_name=:n, location=:l, task_status=:s, 
                            before_photo=:bp, after_photo=:ap WHERE id=:id"""),
                            {"n": en, "l": el, "s": es, "bp": b_final, "ap": a_final, "id": row['id']})
                        session.commit()
                    st.rerun()

        # --- ADMIN FEEDBACK SECTION ---
        st.divider()
        st.write(f"**Admin Rating:** {row['rating']}/10 ⭐")
        st.write(f"**Admin Comment:** {row['admin_comment']}")
        
        if is_adm:
            with st.popover("⭐ Review Task (Admin Only)"):
                new_rating = st.slider("Rating", 0, 10, int(row['rating']), key=f"r_{row['id']}")
                new_fb = st.text_area("Admin Feedback", value=row['admin_comment'], key=f"af_{row['id']}")
                if st.button("Save Review", key=f"srb_{row['id']}"):
                    with conn.session as session:
                        session.execute(text("UPDATE tasks SET rating=:r, admin_comment=:c WHERE id=:id"), 
                                        {"r": new_rating, "c": new_fb, "id": row['id']})
                        session.commit()
                    st.rerun()
