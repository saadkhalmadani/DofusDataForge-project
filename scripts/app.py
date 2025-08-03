import os
import pandas as pd
import streamlit as st
import psycopg2

# ===== Paths =====
CSV_PATH = "download/archimonsters.csv"
IMAGE_FOLDER = "download/Images"
MONSTERS_PER_PAGE = 12

# Ensure image folder exists (ignore errors if read-only)
try:
    os.makedirs(IMAGE_FOLDER, exist_ok=True)
except Exception:
    pass

# ===== Load CSV =====
if not os.path.exists(CSV_PATH):
    st.error(f"❌ File not found: {CSV_PATH}")
    st.stop()

df = pd.read_csv(CSV_PATH)
df["level_num"] = df["level"].astype(str).str.extract(r'(\d+)')[0].fillna(0).astype(int)

# ===== Page config =====
st.set_page_config(page_title="Dofus Archimonsters Viewer", layout="wide")
st.title("🧟‍♂️ Dofus Archimonsters Viewer")
st.caption("Browse monsters scraped from Dofus Touch")

# ===== DB connection string =====
def get_db_uri():
    # Try Streamlit secrets first
    if "db" in st.secrets and "uri" in st.secrets["db"]:
        return st.secrets["db"]["uri"]
    # Else fallback for local dev from env var
    return os.getenv("DATABASE_URL", "")

DB_URI = get_db_uri()
if not DB_URI:
    st.error("❌ Database URI not found. Set Streamlit secrets or DATABASE_URL environment variable.")
    st.stop()

# ===== DB queries =====
@st.cache_data(ttl=300)
def get_all_users():
    try:
        with psycopg2.connect(DB_URI) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT user_id FROM user_monsters ORDER BY user_id;")
                return [row[0] for row in cur.fetchall()]
    except Exception as e:
        st.error(f"❌ Error loading users: {e}")
        return []

@st.cache_data(ttl=300)
def load_owned_monsters(user_id):
    try:
        with psycopg2.connect(DB_URI) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT monster_name, quantity FROM user_monsters
                    WHERE user_id = %s AND quantity > 0
                """, (user_id,))
                rows = cur.fetchall()
                return {name: qty for name, qty in rows}
    except Exception as e:
        st.error(f"❌ Error loading ownership: {e}")
        return {}

# ===== Sidebar =====
users = get_all_users()
selected_user = st.sidebar.selectbox("👤 Select User", users if users else ["anonymous"])
ownership_filter = st.sidebar.radio("🎯 Filter by Ownership", ["All", "Owned", "Not Owned"])
search_term = st.sidebar.text_input("🔍 Search monster by name").strip()
level_range = st.sidebar.slider("🧪 Level Range", 0, 200, (0, 200))

owned_dict = load_owned_monsters(selected_user)
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

# ===== Pagination =====
total_pages = (len(filtered_df) - 1) // MONSTERS_PER_PAGE + 1
page_number = st.number_input("📄 Page", min_value=1, max_value=max(total_pages, 1), step=1)

start = (page_number - 1) * MONSTERS_PER_PAGE
end = start + MONSTERS_PER_PAGE
paginated_df = filtered_df.iloc[start:end]

# ===== Display monsters =====
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
        if row["name"] in owned_dict:
            st.caption(f"🎚️ {row['level']} | ✅ Owned x{owned_dict[row['name']]}")
        else:
            st.caption(f"🎚️ {row['level']} | ❌ Not Owned")

st.markdown("---")
st.success(f"✅ Showing {len(paginated_df)} of {len(filtered_df)} matching monsters.")
st.info(f"📊 {selected_user} owns {len(owned_names)} out of {len(df)} monsters.")
