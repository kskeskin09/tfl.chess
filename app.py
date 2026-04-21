"""
app.py — Chess League Management System
Main Streamlit entry point.

Run with:  streamlit run app.py
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

# ── Page config (must be the very first Streamlit call) ───────────────────────
st.set_page_config(
    page_title="Chess League",
    page_icon="♟️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Imports after page config ─────────────────────────────────────────────────
from auth import current_user, is_admin, is_logged_in, logout, try_login
from config import (
    BYE_PLAYER,
    LEAGUE_NAMES,
    PROMOTION_RELEGATION_COUNT,
    SEASON_DURATION_HOURS,
)
from db import (
    apply_promotion_relegation,
    auto_complete_bye_matches,
    clear_matches,
    clear_results,
    get_all_users,
    get_season,
    get_standings,
    insert_matches,
    reset_all_points,
    upsert_season,
)
from scheduler import generate_fixtures
from ui.components import render_countdown, render_leaderboard
from ui.dashboard import render_dashboard
from ui.admin import render_admin


# ── Custom CSS ────────────────────────────────────────────────────────────────

def _inject_css() -> None:
    st.markdown(
        """
        <style>
        /* ── Global ── */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

        html, body, [class*="css"] {
            font-family: 'Inter', sans-serif;
        }

        /* ── Sidebar ── */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f1117 0%, #1a1d2e 100%);
            border-right: 1px solid #2a2d3e;
        }
        [data-testid="stSidebar"] * {
            color: #e0e0e0 !important;
        }

        /* ── Main background ── */
        .main .block-container {
            background: #0f1117;
            color: #e0e0e0;
            padding-top: 2rem;
        }

        /* ── Metrics ── */
        [data-testid="stMetricValue"] {
            font-size: 1.6rem !important;
            font-weight: 700 !important;
            color: #f0c040 !important;
        }
        [data-testid="stMetricLabel"] {
            color: #aaa !important;
        }

        /* ── Buttons ── */
        .stButton > button {
            border-radius: 8px;
            font-weight: 600;
            transition: all 0.2s ease;
        }
        .stButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(240, 192, 64, 0.3);
        }

        /* ── Divider ── */
        hr {
            border-color: #2a2d3e !important;
            margin: 1.2rem 0 !important;
        }

        /* ── Cards / expanders ── */
        [data-testid="stExpander"] {
            background: #1a1d2e;
            border: 1px solid #2a2d3e;
            border-radius: 10px;
        }

        /* ── Dataframe ── */
        [data-testid="stDataFrame"] {
            border-radius: 8px;
        }

        /* ── Info / warning / error ── */
        [data-testid="stAlert"] {
            border-radius: 8px;
        }

        /* ── Radio ── */
        [data-testid="stRadio"] label {
            font-weight: 500;
        }

        /* ── Headings ── */
        h1, h2, h3, h4 { color: #ffffff !important; }

        /* ── Sidebar logo text ── */
        .sidebar-title {
            font-size: 1.4rem;
            font-weight: 700;
            color: #f0c040 !important;
            letter-spacing: 1px;
            text-align: center;
            padding: 10px 0 6px 0;
        }
        .sidebar-subtitle {
            font-size: 0.75rem;
            color: #888 !important;
            text-align: center;
            margin-bottom: 16px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ── Season auto-cycle ─────────────────────────────────────────────────────────

def _check_and_auto_cycle() -> None:
    """
    Called on every page load.
    If the current season's end time has passed, automatically run
    end-of-season logic and start a fresh season.
    """
    try:
        season = get_season()
    except Exception:
        return  # get_season() already calls st.stop() on APIError; this is belt-and-suspenders

    if not season or not season.get("active"):
        return

    try:
        end_dt = datetime.fromisoformat(season["season_end"])
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
    except Exception:
        return

    if datetime.now(timezone.utc) < end_dt:
        return  # Season still running — nothing to do

    # ── Season has ended → cycle ──────────────────────────────────────────────
    # Mark inactive first to prevent race conditions
    from db import set_season_inactive
    set_season_inactive()

    auto_complete_bye_matches()
    apply_promotion_relegation(LEAGUE_NAMES, PROMOTION_RELEGATION_COUNT)
    reset_all_points()
    clear_results()
    clear_matches()

    now = datetime.now(timezone.utc)
    new_end = now + timedelta(hours=SEASON_DURATION_HOURS)

    all_users = get_all_users()
    league_players: dict[str, list[str]] = {lg: [] for lg in LEAGUE_NAMES}
    for u in all_users:
        if u["league"] in league_players:
            league_players[u["league"]].append(u["name"])

    all_rows: list[dict] = []
    for idx, lg in enumerate(LEAGUE_NAMES):
        players = league_players.get(lg, [])
        if len(players) >= 2:
            rows = generate_fixtures(lg, idx, players, now, new_end)
            all_rows.extend(rows)

    if all_rows:
        insert_matches(all_rows)

    upsert_season(
        {
            "season_number": season.get("season_number", 1) + 1,
            "season_start": now.isoformat(),
            "season_end": new_end.isoformat(),
            "active": True,
        }
    )
    st.toast("🔄 New season started automatically!", icon="♟️")


# ── Sidebar ───────────────────────────────────────────────────────────────────

def _render_sidebar() -> None:
    with st.sidebar:
        # Logo / title
        st.markdown(
            "<div class='sidebar-title'>♟️ Chess League</div>"
            "<div class='sidebar-subtitle'>Management System</div>",
            unsafe_allow_html=True,
        )
        st.divider()

        if not is_logged_in():
            _render_login_form()
            return

        user = current_user()
        st.markdown(
            f"👤 **{user['name']}**"
            + (f"  \n🏷️ {user['league']}" if user.get("league") else "  \n🛡️ Admin"),
        )
        st.divider()

        # Navigation
        if is_admin():
            pages = ["Admin Dashboard"]
        else:
            pages = ["My Dashboard"]

        page = st.radio("Navigate", pages, label_visibility="collapsed")
        st.session_state["page"] = page

        st.divider()

        # Season countdown
        season = get_season()
        if season and season.get("active"):
            render_countdown(season["season_end"])

        # League standings selector (visible to everyone)
        st.markdown("#### 📊 League Standings")
        selected_lg = st.selectbox(
            "View league", LEAGUE_NAMES, label_visibility="collapsed"
        )
        render_leaderboard(
            selected_lg,
            highlight=user["name"] if not is_admin() else None,
        )

        st.divider()
        if st.button("🚪 Logout", use_container_width=True):
            logout()
            st.rerun()


def _render_login_form() -> None:
    st.markdown("#### 🔐 Login")
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Username", placeholder="Enter your name…")
        password = st.text_input("Password", type="password", placeholder="••••••••")
        submitted = st.form_submit_button("Login", use_container_width=True)

    if submitted:
        if not username or not password:
            st.error("Please enter username and password.")
        else:
            ok, msg = try_login(username, password)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)


# ── Main content ──────────────────────────────────────────────────────────────

def _render_main() -> None:
    if not is_logged_in():
        _render_welcome()
        return

    page = st.session_state.get("page", "My Dashboard")

    if page == "Admin Dashboard":
        render_admin()
    else:
        render_dashboard()

    # Auto-refresh every 60 seconds so countdown stays live
    st.markdown(
        """
        <script>
        setTimeout(function() { window.location.reload(); }, 60000);
        </script>
        """,
        unsafe_allow_html=True,
    )


def _render_welcome() -> None:
    st.markdown(
        """
        <div style='text-align:center; padding: 80px 20px'>
            <div style='font-size:5rem'>♟️</div>
            <h1 style='font-size:2.8rem; margin-bottom:8px'>Chess League</h1>
            <p style='color:#aaa; font-size:1.1rem; max-width:520px; margin:0 auto 32px'>
                A multi-league chess management system with automated round-robin
                scheduling, promotion &amp; relegation, and live standings.
            </p>
            <p style='color:#666'>← Log in using the sidebar to get started.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── App entry ─────────────────────────────────────────────────────────────────

def main() -> None:
    _inject_css()
    _check_and_auto_cycle()
    _render_sidebar()
    _render_main()


main()
