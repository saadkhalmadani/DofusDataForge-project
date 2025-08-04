import os
import pandas as pd
import streamlit as st
import psycopg2
from dotenv import load_dotenv
from urllib.parse import urlparse

# ====== Load environment variables ======
load_dotenv()

CSV_PATH = "download/archimonsters.csv"
IMAGE_FOLDER = "download/Images"
MONSTERS_PER_PAGE = 12

# ====== DB Connection Helper ======
def get_db_connection():
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        parsed = urlparse(database_url)
        return psycopg2.connect(
            dbname=parsed.path.lstrip("/"),
            user=parsed.username,
            password=parsed.password,
            host=parsed.hostname,
            port=parsed.port or 5432
        )
    else:
        return psycopg2.connect(
            dbname=os.getenv("POSTGRES_DB", "dofus_user"),
            user=os.getenv("POSTGRES_USER", "dofus_user"),
            password=os.getenv("POSTGRES_PASSWORD", "dofus_pass"),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", "5432")
        )

# ====== Validate User ======
def validate_user(username, password):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT password FROM users WHERE username = %s", (username,))
                row = cur.fetchone()
                # TODO: Replace with hashed password check in production
                return row and row[0] == password
    except Exception as e:
        st.error(f"❌ Login error: {e}")
        return False

def get_user_id_by_username(username):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
            if row:
                return row[0]
            else:
                raise ValueError(f"User {username} not found in DB")

# ====== Monster Ownership ======
def load_owned_monsters(user_id):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT monster_name, quantity FROM user_monsters
                    WHERE user_id = %s AND quantity > 0
                """, (user_id,))
                return dict(cur.fetchall())
    except Exception as e:
        st.error(f"❌ Error loading ownership: {e}")
        return {}

def update_quantity(user_id, monster_name, change):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO user_monsters (user_id, monster_name, quantity)
                    VALUES (%s, %s, GREATEST(%s, 0))
                    ON CONFLICT (user_id, monster_name) DO UPDATE
                    SET quantity = GREATEST(user_monsters.quantity + %s, 0);
                """, (user_id, monster_name, change, change))
                conn.commit()
    except Exception as e:
        st.error(f"❌ Update error: {e}")

# ====== Streamlit Setup ======
st.set_page_config(page_title="Dofus Archimonsters Viewer", layout="wide")
st.title("🧟‍♂️ Dofus Archimonsters Viewer")

# ====== Load CSV ======
if not os.path.exists(CSV_PATH):
    st.error(f"❌ File not found: {CSV_PATH}")
    st.stop()

df = pd.read_csv(CSV_PATH)
df["level_num"] = df["level"].astype(str).str.extract(r'(\d+)')[0].fillna(0).astype(int)

# ====== Login Form ======
if "user_id" not in st.session_state:
    st.session_state.user_id = None
    st.session_state.username = ""

st.sidebar.markdown("## 🔐 Login")
username_input = st.sidebar.text_input("Username")
password_input = st.sidebar.text_input("Password", type="password")
login_button = st.sidebar.button("🔓 Login")

if login_button:
    if validate_user(username_input.strip(), password_input.strip()):
        user_id = get_user_id_by_username(username_input.strip())
        if user_id:
            st.session_state.user_id = user_id
            st.session_state.username = username_input.strip()
            st.success(f"✅ Logged in as {st.session_state.username}")
    else:
        st.warning("❌ Invalid username or password.")
        st.session_state.user_id = None

if not st.session_state.user_id:
    st.warning("👤 Please log in to continue.")
    st.stop()

# ====== Filters ======
st.caption(f"Logged in as: `{st.session_state.username}`")

ownership_filter = st.sidebar.radio("🎯 Filter by Ownership", ["All", "Owned", "Not Owned"])
search_term = st.sidebar.text_input("🔍 Search monster by name").strip()
level_range = st.sidebar.slider("🧪 Level Range", 0, 200, (0, 200))

# ====== Filter Logic ======
owned_dict = load_owned_monsters(st.session_state.user_id)
owned_names = set(owned_dict.keys())

filtered_df = df[
    df["level_num"].between(level_range[0], level_range[1]) &
    df["name"].str.contains(search_term, case=False, na=False)
].copy()

if ownership_filter == "Owned":
    filtered_df = filtered_df[filtered_df["name"].isin(owned_names)]
elif ownership_filter == "Not Owned":
    filtered_df = filtered_df[~filtered_df["name"].isin(owned_names)]

filtered_df.reset_index(drop=True, inplace=True)

# ====== Pagination ======
total_pages = (len(filtered_df) - 1) // MONSTERS_PER_PAGE + 1
page_number = st.number_input("📄 Page", min_value=1, max_value=max(total_pages, 1), step=1)
start = (page_number - 1) * MONSTERS_PER_PAGE
end = start + MONSTERS_PER_PAGE
paginated_df = filtered_df.iloc[start:end]

# ====== Display Monsters ======
cols = st.columns(3)
for idx, row in paginated_df.iterrows():
    col = cols[idx % 3]
    with col:
        st.subheader(row["name"])
        img_path = row["local_image"]
        if isinstance(img_path, str) and os.path.exists(img_path):
            st.image(img_path)
        else:
            st.warning("⚠️ Image not found")

        qty = owned_dict.get(row["name"], 0)
        st.caption(f"🎚️ {row['level']} | {'✅ Owned x' + str(qty) if qty else '❌ Not Owned'}")

        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("➕", key=f"inc_{idx}", help="Increase quantity"):
                update_quantity(st.session_state.user_id, row["name"], 1)
                st.experimental_rerun()
        with col2:
            if st.button("➖", key=f"dec_{idx}", help="Decrease quantity"):
                update_quantity(st.session_state.user_id, row["name"], -1)
                st.experimental_rerun()

# ====== Summary ======
total_owned = len(owned_names)
total_available = len(df)
st.markdown("---")
st.success(f"✅ Showing {len(paginated_df)} of {len(filtered_df)} monsters.")
st.info(f"📊 `{st.session_state.username}` owns {total_owned} out of {total_available} monsters.")

# ====== Export Owned Monsters as CSV ======
if total_owned > 0:
    owned_df = df[df["name"].isin(owned_dict.keys())].copy()
    owned_df["quantity"] = owned_df["name"].map(owned_dict)

    csv_data = owned_df.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="📤 Download Owned Monsters as CSV",
        data=csv_data,
        file_name=f"{st.session_state.username}_owned_monsters.csv",
        mime="text/csv"
    )
