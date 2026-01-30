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
                technician TEXT, user_comment TEXT DEFAULT '',
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
    
    # --- ENHANCED EXCEL EXPORT WITH HYPERLINKS ---
    if st.sidebar.button("📥 Export Comprehensive Report"):
        df = conn.query("SELECT * FROM tasks", ttl=0)
        if not df.empty:
            excel_buffer = io.BytesIO()
            # Clean status for Excel (remove emojis)
            df['task_status'] = df['task_status'].str.replace('🟡 ', '').str.replace('🟠 ', '').str.replace('🟢 ', '')
            
            with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
                df.to_excel(writer, sheet_name='Report', index=False)
                workbook = writer.book
                worksheet = writer.sheets['Report']
                
                # Formats
                link_fmt = workbook.add_format({'color': 'blue', 'underline': 1})
                header_fmt = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1})
                
                # Apply conditional formatting for Status
                worksheet.conditional_format('C2:C1000', {'type': 'cell', 'criteria': '==', 'value': '"Completed"', 'format': workbook.add_format({'bg_color': '#C6EFCE'})})
                worksheet.conditional_format('C2:C1000', {'type': 'cell', 'criteria': '==', 'value': '"In Progress"', 'format': workbook.add_format({'bg_color': '#FFEB9C'})})

                # Write Hyperlinks for images
                for i, row in df.iterrows():
                    # Photos are in columns G (Before) and H (After) - indexes 6, 7
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
            st.sidebar.download_button("💾 Download ZIP", zip_buffer.getvalue(), "Export_Package.zip")

    # USER MANAGEMENT (Edit Names & Passwords)
    with st.sidebar.expander("👥 User Management"):
        st.write("**Edit User Credentials:**")
        all_u = conn.query("SELECT * FROM users", ttl=0)
        for _, urow in all_u.iterrows():
            with st.container(border=True):
                new_uname = st.text_input("Name", value=urow['username'], key=f"un_{urow['username']}")
                new_pass = st.text_input("Pass", value=urow['password'], key=f"pw_{urow['username']}")
                if st.button("Save", key=f"sv_{urow['username']}"):
                    with conn.session as session:
                        session.execute(text("UPDATE users SET username=:nu, password=:np WHERE username=:ou"), 
                                        {"nu": new_uname, "np": new_pass, "ou": urow['username']})
                        session.commit()
                    st.rerun()

# ---- 5. UI: LOG NEW TASK (Professional Date/Time) ----
st.title("👨‍🔧 Maintenance Portal")
with st.expander("➕ Create New Entry", expanded=True):
    with st.form("new_task"):
        c1, c2 = st.columns(2)
        n = c1.text_input("Project Name")
        l = c2.text_input("📍 Location")
        
        c3, c4, c5 = st.columns(3)
        s = c3.selectbox("Status", ["🟡 In Progress", "🟠 Awaiting Parts", "🟢 Completed"])
        # Standard Datetime Pickers
        sd = c4.date_input("Start Date")
        st_t = c4.time_input("Start Time")
        ed = c5.date_input("End Date")
        et_t = c5.time_input("End Time")
        
        desc = st.text_area("Description")
        u_comm = st.text_area("Tech Notes")
        
        img_b = st.file_uploader("Before Photos", accept_multiple_files=True)
        img_a = st.file_uploader("After Photos", accept_multiple_files=True)
        
        if st.form_submit_button("Submit"):
            b_names = save_files(img_b, "before")
            a_names = save_files(img_a, "after")
            st_dt = f"{sd} {st_t}"
            en_dt = f"{ed} {et_t}"
            with conn.session as session:
                session.execute(text("""INSERT INTO tasks (task_name, location, task_status, task_desc_text, 
                    before_photo, after_photo, technician, user_comment, start_time, end_time) 
                    VALUES (:n, :l, :s, :d, :bp, :ap, :t, :uc, :st, :et)"""),
                    {"n": n, "l": l, "s": s, "d": desc, "bp": b_names, "ap": a_names, 
                     "t": st.session_state.username, "uc": u_comm, "st": st_dt, "et": en_dt})
                session.commit()
            st.rerun()

# ---- 6. HISTORY & FULL EDITING ----
st.header("📋 Active Log")
df_tasks = conn.query("SELECT * FROM tasks ORDER BY id DESC", ttl=0)

for _, row in df_tasks.iterrows():
    is_adm = st.session_state.user_role == "admin"
    can_edit = is_adm or (st.session_state.username == row['technician'])
    
    with st.container(border=True):
        if can_edit:
            with st.expander(f"📝 Edit: {row['task_name']}", expanded=False):
                en = st.text_input("Name", value=row['task_name'], key=f"en_{row['id']}")
                el = st.text_input("Location", value=row['location'], key=f"el_{row['id']}")
                es = st.selectbox("Status", ["🟡 In Progress", "🟠 Awaiting Parts", "🟢 Completed"], 
                                  index=["🟡 In Progress", "🟠 Awaiting Parts", "🟢 Completed"].index(row['task_status']), 
                                  key=f"es_{row['id']}")
                
                # Split strings back to date/time objects for widgets
                try:
                    curr_st = datetime.strptime(row['start_time'], '%Y-%m-%d %H:%M:%S')
                    curr_en = datetime.strptime(row['end_time'], '%Y-%m-%d %H:%M:%S')
                except:
                    curr_st = datetime.now()
                    curr_en = datetime.now()

                c_s1, c_s2 = st.columns(2)
                nsd = c_s1.date_input("Start Date", value=curr_st, key=f"nsd_{row['id']}")
                nst = c_s1.time_input("Start Time", value=curr_st, key=f"nst_{row['id']}")
                ned = c_s2.date_input("End Date", value=curr_en, key=f"ned_{row['id']}")
                net = c_s2.time_input("End Time", value=curr_en, key=f"net_{row['id']}")

                if st.button("Save Changes", key=f"btn_{row['id']}"):
                    with conn.session as session:
                        session.execute(text("""UPDATE tasks SET task_name=:n, location=:l, task_status=:s, 
                            start_time=:st, end_time=:et WHERE id=:id"""),
                            {"n": en, "l": el, "s": es, "st": f"{nsd} {nst}", "et": f"{ned} {net}", "id": row['id']})
                        session.commit()
                    st.rerun()

        # Display View
        st.subheader(f"{row['task_status']} | {row['task_name']}")
        st.caption(f"📍 {row['location']} | 📅 {row['start_time']} to {row['end_time']}")
        
        # Images Display/Delete
        for label, col_key in [("Before", "before_photo"), ("After", "after_photo")]:
            if row[col_key]:
                st.write(f"**{label}:**")
                imgs = row[col_key].split(",")
                p_cols = st.columns(5)
                for i, img in enumerate(imgs):
                    with p_cols[i % 5]:
                        st.image(os.path.join(UPLOAD_DIR, img))
                        if can_edit and st.button("Delete", key=f"p_{row['id']}_{col_key}_{i}"):
                            imgs.pop(i)
                            update_task_field(row['id'], col_key, ",".join(imgs) if imgs else None)
                            st.rerun()
