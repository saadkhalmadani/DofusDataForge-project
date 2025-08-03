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

# ====== Authentication ======
if "user_id" not in st.session_state:
    st.session_state.user_id = ""

st.sidebar.markdown("## 🔐 Login")
username = st.sidebar.text_input("Username", value=st.session_state.user_id)
login_button = st.sidebar.button("🔓 Login")

if login_button:
    st.session_state.user_id = username.strip()
    st.success(f"✅ Logged in as {st.session_state.user_id}")

if not st.session_state.user_id:
    st.warning("👤 Please log in to manage ownership.")
    st.stop()

current_user = st.session_state.user_id

# ====== Load CSV ======
if not os.path.exists(CSV_PATH):
    st.error(f"❌ File not found: {CSV_PATH}")
    st.stop()

df = pd.read_csv(CSV_PATH)

# ====== Extract numeric level ======
df["level_num"] = df["level"].astype(str).str.extract(r'(\d+)')[0].fillna(0).astype(int)

# ====== Streamlit Setup ======
st.set_page_config(page_title="Dofus Archimonsters Viewer", layout="wide")
st.title("🧟‍♂️ Dofus Archimonsters Viewer")
st.caption(f"Logged in as: `{current_user}`")

# ====== Ownership Loading/Updating ======
@st.cache_data(ttl=300)
def get_all_users():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT user_id FROM user_monsters ORDER BY user_id;")
                return [row[0] for row in cur.fetchall()]
    except Exception as e:
        st.error(f"❌ Error loading users: {e}")
        return []

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

# ====== Sidebar Filters ======
ownership_filter = st.sidebar.radio("🎯 Filter by Ownership", ["All", "Owned", "Not Owned"])
search_term = st.sidebar.text_input("🔍 Search monster by name").strip()
level_range = st.sidebar.slider("🧪 Level Range", 0, 200, (0, 200))

# ====== Filtering Logic ======
owned_dict = load_owned_monsters(current_user)
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

# ====== Display Grid ======
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
            if st.button(f"➕ {row['name']}", key=f"inc_{idx}"):
                update_quantity(current_user, row["name"], 1)
                st.rerun()
        with col2:
            if st.button(f"➖ {row['name']}", key=f"dec_{idx}"):
                update_quantity(current_user, row["name"], -1)
                st.rerun()

# ====== Summary ======
total_owned = len(owned_names)
total_available = len(df)
st.markdown("---")
st.success(f"✅ Showing {len(paginated_df)} of {len(filtered_df)} monsters.")
st.info(f"📊 `{current_user}` owns {total_owned} out of {total_available} monsters.")
