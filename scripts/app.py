import os
from io import BytesIO
import pandas as pd
import streamlit as st
import psycopg2
from dotenv import load_dotenv
from urllib.parse import urlparse
from datetime import datetime
from PIL import Image

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

def safe_rerun():
    if hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    elif hasattr(st, "rerun"):
        st.rerun()
    else:
        st.warning("⚠️ Please manually refresh the page.")

# ====== Streamlit Setup ======
st.set_page_config(
    page_title="Dofus Archimonsters Viewer",
    page_icon="🧟‍♂️",
    layout="wide",
    menu_items={
        "Get Help": "https://streamlit.io",
        "About": "Dofus Archimonsters Viewer — browse, track, and export your collection."
    },
)
st.title("🧟‍♂️ Dofus Archimonsters Viewer")

# Global styles
st.markdown(
    """
    <style>
    .monster-card {
        border: 1px solid #e6e6e6;
        border-radius: 10px;
        padding: 0.75rem;
        margin-bottom: 1rem;
        background: #ffffffaa;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
        transition: box-shadow .2s ease, transform .1s ease;
    }
    .monster-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.12); transform: translateY(-2px); }
    .monster-title { font-weight: 700; margin: 0.25rem 0 0.5rem 0; }
    .monster-img img { object-fit: contain; width: 100%; height: auto; max-height: 180px; border-radius: 8px; background: #f8f9fa; }
    .mon-meta { color: #666; font-size: 0.9rem; margin-top: .25rem; }
    .filters .stSlider > div > div { padding-top: 0.25rem; }
    .muted { color:#888; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ====== Load CSV ======
if not os.path.exists(CSV_PATH):
    st.error(f"❌ File not found: {CSV_PATH}")
    st.stop()

@st.cache_data(show_spinner=False)
def load_monsters_csv(path: str) -> pd.DataFrame:
    _df = pd.read_csv(path)
    _df["level_num"] = _df["level"].astype(str).str.extract(r'(\d+)')[0].fillna(0).astype(int)
    return _df

df = load_monsters_csv(CSV_PATH)

# ====== Login Form ======
if "user_id" not in st.session_state:
    st.session_state.user_id = None
    st.session_state.username = ""

st.sidebar.markdown("## 🔐 Login")
username_input = st.sidebar.text_input("Username", value=st.session_state.username)
password_input = st.sidebar.text_input("Password", type="password")
cols_login = st.sidebar.columns([1,1])
with cols_login[0]:
    login_button = st.button("🔓 Login")
with cols_login[1]:
         logout_button = st.button("🚪 Logout")

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

if logout_button:
    st.session_state.user_id = None
    st.session_state.username = ""
    st.toast("Logged out.")

if not st.session_state.user_id:
    st.warning("👤 Please log in to continue.")
    st.stop()

# ====== Filters ======
st.caption(f"Logged in as: `{st.session_state.username}`")

with st.sidebar:
    st.markdown("### 🎛️ Filters", help="Refine the list of monsters")
    # Apply any pending resets BEFORE creating widgets with those keys
    if (
        "pending_image_height" in st.session_state
        or "pending_size_preset" in st.session_state
        or "pending_cols_per_row" in st.session_state
    ):
        if "pending_size_preset" in st.session_state:
            st.session_state["last_size_preset"] = st.session_state.pop("pending_size_preset")
        if "pending_image_height" in st.session_state:
            st.session_state["image_height"] = st.session_state.pop("pending_image_height")
        if "pending_cols_per_row" in st.session_state:
            st.session_state["cols_per_row"] = st.session_state.pop("pending_cols_per_row")
    ownership_filter = st.radio("🎯 Ownership", ["All", "Owned", "Not Owned"], horizontal=True)
    search_term = st.text_input("🔍 Search", placeholder="Type a monster name...").strip()
    level_range = st.slider("🧪 Level Range", 0, 200, (0, 200))
    show_missing_images = st.checkbox("🖼️ Only show missing images", value=False)
    sort_by = st.selectbox("↕️ Sort by", ["Name", "Level"], index=0)
    sort_asc = st.toggle("⬆️ Ascending", value=True)
    per_page = st.select_slider("📦 Items per page", options=[6, 9, 12, 15, 18, 24], value=12)
    st.markdown("---")
    _size_options = ["XS", "Small", "Medium", "Large"]
    _preset_map = {"XS": 60, "Small": 90, "Medium": 120, "Large": 160}
    _default_preset = st.session_state.get("last_size_preset", "XS")
    _initial_index = _size_options.index(_default_preset) if _default_preset in _size_options else _size_options.index("XS")
    size_preset = st.selectbox("🧩 Thumbnail size", _size_options, index=_initial_index, help="Quick presets for thumbnail size")
    if "last_size_preset" not in st.session_state:
        st.session_state["last_size_preset"] = size_preset
    if "image_height" not in st.session_state:
        st.session_state["image_height"] = _preset_map[st.session_state["last_size_preset"]]
    if st.session_state.get("last_size_preset") != size_preset:
        st.session_state["image_height"] = _preset_map[size_preset]
        st.session_state["last_size_preset"] = size_preset
    image_height = st.slider(
        "🖼️ Image height (px)",
        min_value=60,
        max_value=320,
        step=10,
        key="image_height",
    )
    if "cols_per_row" not in st.session_state:
        st.session_state["cols_per_row"] = 2
    cols_per_row = st.slider("🧱 Columns per row", min_value=2, max_value=6, step=1, key="cols_per_row")
    compact_mode = st.toggle("📏 Compact mode", value=True, help="Reduce paddings and fonts for dense layout")
    clear_filters = st.button("🧹 Clear filters")

if clear_filters:
    search_term = ""
    level_range = (0, 200)
    ownership_filter = "All"
    show_missing_images = False
    sort_by, sort_asc = "Name", True
    per_page = 12
    # Defer changing widget-backed keys until next run to avoid Streamlit API exception
    st.session_state["pending_image_height"] = 60
    st.session_state["pending_size_preset"] = "XS"
    st.session_state["pending_cols_per_row"] = 2
    st.toast("Filters cleared")
    safe_rerun()

# Dynamic style overrides
compact_css = """
.monster-card { padding: 0.5rem; margin-bottom: 0.5rem; }
.monster-title { font-size: 0.95rem; }
.mon-meta { font-size: 0.8rem; }
/* General buttons */
.stButton > button,
div[data-testid="stButton"] > button,
div[data-testid="baseButton-secondary"] > button,
div[data-testid="baseButton-primary"] > button,
div[data-testid="stDownloadButton"] > button,
div[data-testid="stPopoverButton"] > button,
button[kind="secondary"] {
    padding: 0.12rem 0.28rem;
    min-height: 20px;
    height: 20px;
        line-height: 1;
    font-size: 0.72rem;
    border-radius: 6px;
}
    /* Card-local buttons even smaller */
   .monster-card .stButton > button { padding: 0.06rem 0.22rem; min-height: 18px; height: 18px; font-size: 0.7rem; min-width: 26px; }
/* Number input (pager) */
div[data-testid="stNumberInput"] input {
        padding: 0.12rem 0.35rem;
        height: 26px;
        font-size: 0.8rem;
}
div[data-testid="stNumberInput"] button {
    transform: scale(0.9);
}
/* Narrow number input inside cards */
.monster-card div[data-testid=\"stNumberInput\"] input { width: 64px; }
/* Reduce column gutters a bit */
div[data-testid=\"column\"] { padding-left: 0.25rem; padding-right: 0.25rem; }
"""

st.markdown(
    f"""
    <style>
    .monster-img img {{ max-height: {image_height}px; }}
    {compact_css if compact_mode else ''}
    </style>
    """,
    unsafe_allow_html=True,
)

# ====== Filter Logic ======
owned_dict = load_owned_monsters(st.session_state.user_id)
owned_names = set(owned_dict.keys())

filtered_df = df[
    df["level_num"].between(level_range[0], level_range[1]) &
    df["name"].str.contains(search_term, case=False, na=False)
].copy()

if show_missing_images:
    filtered_df = filtered_df[~(filtered_df["local_image"].astype(str).apply(lambda p: os.path.exists(p)))]

if ownership_filter == "Owned":
    filtered_df = filtered_df[filtered_df["name"].isin(owned_names)]
elif ownership_filter == "Not Owned":
    filtered_df = filtered_df[~filtered_df["name"].isin(owned_names)]

filtered_df.reset_index(drop=True, inplace=True)

# Sorting
if sort_by == "Name":
    filtered_df.sort_values(by="name", ascending=sort_asc, inplace=True, kind="stable")
else:
    filtered_df.sort_values(by="level_num", ascending=sort_asc, inplace=True, kind="stable")

# ====== Pagination ======
total_pages = (len(filtered_df) - 1) // max(per_page, 1) + 1

# Keep page number in session
if "page_number" not in st.session_state:
    st.session_state.page_number = 1

def set_page(n: int):
    st.session_state.page_number = int(max(1, min(n, max(total_pages, 1))))

# Reset page if filter results smaller than current page
if st.session_state.page_number > total_pages:
    set_page(1)

pager_cols = st.columns([1, 2, 1, 3])
with pager_cols[0]:
    if st.button("◀", disabled=st.session_state.page_number <= 1, help="Previous page"):
        set_page(st.session_state.page_number - 1)
with pager_cols[1]:
    st.number_input(
        "📄 Page",
        min_value=1,
        max_value=max(total_pages, 1),
        step=1,
        key="page_number",
    )
with pager_cols[2]:
    if st.button("▶", disabled=st.session_state.page_number >= total_pages, help="Next page"):
        set_page(st.session_state.page_number + 1)
with pager_cols[3]:
    st.caption(f"Page {st.session_state.page_number} of {max(total_pages, 1)} — {len(filtered_df)} results")

start = (st.session_state.page_number - 1) * per_page
end = start + per_page
paginated_df = filtered_df.iloc[start:end]

# ====== Display Monsters ======
@st.cache_data(show_spinner=False)
def load_resized_image(path: str, target_h: int) -> tuple[bytes, int]:
    try:
        with Image.open(path) as im:
            # Preserve aspect ratio based on target height
            w, h = im.size
            if h <= 0:
                return b"", 0
            new_w = max(1, int(w * (target_h / h)))
            # Convert mode for consistent output
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA")
            im = im.resize((new_w, target_h), Image.LANCZOS)
            buf = BytesIO()
            im.save(buf, format="PNG", optimize=True)
            return buf.getvalue(), new_w
    except Exception:
        return b"", 0

tab_browse, tab_stats, tab_table = st.tabs(["🔎 Browse", "📈 Statistics", "📋 Table"])

with tab_browse:
    cols = st.columns(cols_per_row)
    for idx, row in paginated_df.iterrows():
        col = cols[idx % cols_per_row]
        with col:
            st.markdown("<div class='monster-card'>", unsafe_allow_html=True)
            st.markdown(f"<div class='monster-title'>{row['name']}</div>", unsafe_allow_html=True)
            img_path = row["local_image"]
            with st.container():
                if isinstance(img_path, str) and os.path.exists(img_path):
                    st.markdown("<div class='monster-img'>", unsafe_allow_html=True)
                    img_bytes, new_w = load_resized_image(img_path, image_height)
                    if img_bytes:
                        st.image(img_bytes, width=new_w)
                    else:
                        # Fallback to file if resizing failed
                        st.image(img_path, width=int(image_height))
                    st.markdown("</div>", unsafe_allow_html=True)
                else:
                    st.info("🖼️ Image not found", icon="ℹ️")

            qty = owned_dict.get(row["name"], 0)
            st.markdown(
                f"<div class='mon-meta'>🎚️ {row['level']} · "
                + (f"✅ Owned ×{qty}" if qty else "❌ Not Owned")
                + "</div>",
                unsafe_allow_html=True,
            )

            c1, c2, c3 = st.columns([1,1,2])
            with c1:
                if st.button("➕", key=f"inc_{idx}", help="Increase quantity"):
                    update_quantity(st.session_state.user_id, row["name"], 1)
                    st.toast(f"Added 1 to {row['name']}")
                    safe_rerun()
            with c2:
                if st.button("➖", key=f"dec_{idx}", help="Decrease quantity"):
                    update_quantity(st.session_state.user_id, row["name"], -1)
                    st.toast(f"Removed 1 from {row['name']}")
                    safe_rerun()
            with c3:
                with st.popover("⋯", use_container_width=True):
                    st.caption("Quick actions")
                    if st.button("Reset to 0", key=f"reset_{idx}"):
                        # Set to 0 by subtracting current qty if any
                        if qty:
                            update_quantity(st.session_state.user_id, row["name"], -int(qty))
                            st.toast(f"Reset {row['name']} to 0")
                            safe_rerun()
                        else:
                            st.toast("Already 0")
                    set_qty = st.number_input("Set quantity", min_value=0, max_value=999, value=int(qty), key=f"setqty_{idx}")
                    if st.button("Apply", key=f"applyqty_{idx}"):
                        delta = int(set_qty) - int(qty)
                        if delta != 0:
                            update_quantity(st.session_state.user_id, row["name"], delta)
                            st.toast(f"Set {row['name']} to {int(set_qty)}")
                            safe_rerun()
                        else:
                            st.toast("No change")
            st.markdown("</div>", unsafe_allow_html=True)

with tab_stats:
    total_available = len(df)
    unique_owned = len(owned_names)
    total_qty = int(sum(owned_dict.values())) if owned_dict else 0
    missing = total_available - unique_owned
    pct = (unique_owned / total_available) if total_available else 0.0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Monsters", total_available)
    m2.metric("Owned (unique)", unique_owned)
    m3.metric("Owned quantity", total_qty)
    m4.metric("Missing", missing)

    st.progress(pct, text=f"Collection completion: {pct:.1%}")

    st.markdown("### Level distribution (filtered)")
    level_counts = filtered_df.groupby("level_num").size().reset_index(name="count").sort_values("level_num")
    st.bar_chart(level_counts, x="level_num", y="count", height=240)

    st.markdown("### Owned vs Missing (filtered)")
    df_om = filtered_df.assign(is_owned=filtered_df["name"].isin(owned_names))
    own_counts = df_om["is_owned"].value_counts().rename(index={True:"Owned", False:"Missing"})
    st.bar_chart(own_counts, height=200)

with tab_table:
    table_df = filtered_df.copy()
    table_df["owned_qty"] = table_df["name"].map(owned_dict).fillna(0).astype(int)
    st.dataframe(table_df[["name", "level", "level_num", "owned_qty", "local_image"]], use_container_width=True, hide_index=True)
    dl_cols = st.columns([1,1,4])
    with dl_cols[0]:
        st.download_button(
            label="⬇️ Download filtered CSV",
            data=table_df.to_csv(index=False).encode("utf-8"),
            file_name=f"filtered_monsters_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )

# ====== Summary ======
total_owned = len(owned_names)
total_available = len(df)
st.markdown("---")
st.success(f"✅ Showing {len(paginated_df)} of {len(filtered_df)} monsters.")
st.info(f"📊 `{st.session_state.username}` owns {total_owned} out of {total_available} monsters · {total_owned/total_available if total_available else 0:.1%} complete.")

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

# Export missing monsters CSV
missing_names = [n for n in df["name"].tolist() if n not in owned_names]
if len(missing_names) > 0:
    missing_df = df[df["name"].isin(missing_names)].copy()
    miss_csv = missing_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download Missing Monsters as CSV",
        data=miss_csv,
        file_name=f"{st.session_state.username}_missing_monsters.csv",
        mime="text/csv"
    )
