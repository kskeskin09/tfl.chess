"""
ui/dashboard.py — Player dashboard page.
"""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from auth import current_user
from config import BYE_PLAYER
from db import (
    check_and_finalize_match,
    get_current_match,
    get_player_result,
    get_standings,
    get_user,
    upsert_result,
)


def render_dashboard() -> None:
    user = current_user()
    if not user:
        st.error("Not logged in.")
        return

    name: str = user["name"]

    # Refresh user data fresh from DB
    fresh = get_user(name)
    if fresh:
        user = fresh
        st.session_state["user"] = fresh

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown(
        f"""
        <h2 style='margin-bottom:4px'>♟️ Welcome, {name}</h2>
        <p style='color:#aaa; margin-top:0'>
            League: <strong>{user['league']}</strong> &nbsp;|&nbsp;
            Points: <strong>{user['points']}</strong>
        </p>
        """,
        unsafe_allow_html=True,
    )
    st.divider()

    # ── Current match ─────────────────────────────────────────────────────────
    st.subheader("🎯 Your Current Match")
    match = get_current_match(name)

    if match is None:
        st.info("No active match right now. Check back when the next round starts.")
    elif match["status"] == "bye":
        st.warning(
            "⏭️ **You are skipping this round — your score will not change.**\n\n"
            "Sit back and relax while others play!"
        )
    else:
        _render_match_panel(name, match)

    st.divider()

    # ── My rank in current league ─────────────────────────────────────────────
    st.subheader(f"📊 {user['league']} Standings")
    _render_mini_standings(user["league"], highlight=name)


def _render_match_panel(player: str, match: dict) -> None:
    """Show opponent details, result entry, and status for the active match."""
    opponent = match["player2"] if match["player1"] == player else match["player1"]
    deadline_str = match["deadline"]

    try:
        deadline_dt = datetime.fromisoformat(deadline_str)
        if deadline_dt.tzinfo is None:
            deadline_dt = deadline_dt.replace(tzinfo=timezone.utc)
        deadline_fmt = deadline_dt.strftime("%d %b %Y  %H:%M UTC")
    except Exception:
        deadline_fmt = deadline_str

    # Opponent info
    opp_data = get_user(opponent)
    opp_phone = opp_data["phone"] if opp_data else "—"

    col1, col2 = st.columns(2)
    col1.metric("Opponent", opponent)
    col2.metric("Phone", opp_phone)

    st.caption(f"⏰ Round deadline: **{deadline_fmt}**")

    # Disputed warning
    if match["status"] == "disputed":
        st.error(
            "⚠️ **Dispute detected!** Your reported result conflicts with your "
            "opponent's. Please contact the admin for resolution."
        )

    # Existing result
    existing = get_player_result(match["match_id"], player)
    existing_val = existing["result"] if existing else None

    options = ["Win", "Draw", "Loss"]
    default_idx = options.index(existing_val) if existing_val in options else 0

    st.markdown("**Report your result:**")
    chosen = st.radio(
        "What was the outcome for you?",
        options,
        index=default_idx,
        horizontal=True,
        key=f"result_radio_{match['match_id']}",
    )

    col_save, col_status = st.columns([2, 3])
    with col_save:
        if st.button("💾 Save Result", key=f"save_{match['match_id']}", use_container_width=True):
            upsert_result(match["match_id"], player, chosen)
            outcome = check_and_finalize_match(match["match_id"])
            if outcome == "finalized":
                st.success("✅ Both players agree — points have been awarded!")
            elif outcome == "disputed":
                st.error("❌ Conflict detected — match marked as disputed.")
            elif outcome == "waiting":
                st.info("✔️ Result saved. Waiting for opponent to submit.")
            st.rerun()

    with col_status:
        if existing_val:
            st.success(f"Your current report: **{existing_val}**")
        else:
            st.warning("You haven't reported a result yet.")


def _render_mini_standings(league: str, highlight: str) -> None:
    rows = get_standings(league)
    if not rows:
        st.info("No standings available.")
        return

    for p in rows:
        is_me = p["name"] == highlight
        badge = "🟡" if is_me else "⬜"
        st.markdown(
            f"{badge} **#{p['rank']}** &nbsp; {p['name']} "
            f"{'← you' if is_me else ''} &nbsp; `{p['points']} pts`"
        )
