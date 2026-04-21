"""
ui/dashboard.py — Player dashboard page.
"""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from auth import current_user
from config import BYE_PLAYER, LEAGUE_NAMES
from db import (
    check_and_finalize_match,
    get_player_matches,
    get_player_result,
    get_standings,
    get_user,
    upsert_result,
)


def _format_dt(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%d %b %Y  %H:%M UTC")
    except Exception:
        return iso_str


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

    col_main, col_standings = st.columns([2, 1], gap="large")

    with col_standings:
        st.subheader("📊 League Standings")
        
        # Set default index to user's league if it exists in LEAGUE_NAMES
        default_index = LEAGUE_NAMES.index(user["league"]) if user["league"] in LEAGUE_NAMES else 0
        selected_lg = st.selectbox(
            "Select League", 
            LEAGUE_NAMES, 
            index=default_index, 
            label_visibility="collapsed"
        )
        
        rows = get_standings(selected_lg)
        if not rows:
            st.info("No standings available.")
        else:
            st.markdown(
                """
                <style>
                .standings-table { width: 100%; border-collapse: collapse; font-size: 0.95rem; }
                .standings-table th, .standings-table td { padding: 10px 8px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.05); }
                .standings-table th { color: #888; font-weight: 600; text-transform: uppercase; font-size: 0.8rem; letter-spacing: 1px; }
                .highlight-row { background-color: rgba(240, 192, 64, 0.15); font-weight: 600; border-radius: 4px; }
                </style>
                """, unsafe_allow_html=True
            )
            html = "<table class='standings-table'><tr><th>#</th><th>Player</th><th>Points</th></tr>"
            for r in rows:
                cls = "highlight-row" if r["name"] == name else ""
                html += f"<tr class='{cls}'><td>{r['rank']}</td><td>{r['name']}</td><td>{r['points']}</td></tr>"
            html += "</table>"
            st.markdown(html, unsafe_allow_html=True)


    with col_main:
        matches = get_player_matches(name)
        matches.sort(key=lambda x: x["start_time"])
        
        now_iso = datetime.now(timezone.utc).isoformat()
        
        completed = []
        active = None
        upcoming = []
        
        for idx, m in enumerate(matches, 1):
            m["round_num"] = idx
            
            # If match deadline has passed OR both players reported (status='completed')
            if m["deadline"] < now_iso or m["status"] == "completed":
                completed.append(m)
            elif m["start_time"] <= now_iso <= m["deadline"]:
                if active is None:
                    active = m
                else:
                    upcoming.append(m)
            else:
                upcoming.append(m)
                
        total_rounds = len(matches)
        rounds_remaining = total_rounds - len(completed)
        
        st.markdown(f"**Rounds remaining:** {rounds_remaining} / {total_rounds}")
        st.markdown("<br>", unsafe_allow_html=True)
        
        # ── Active Match ──
        if active:
            st.subheader("🎯 Active Round")
            _render_match_panel(name, active)
        elif upcoming:
            st.info(f"Your next match starts on **{_format_dt(upcoming[0]['start_time'])}**.")
            
        st.markdown("<hr style='opacity: 0.2'>", unsafe_allow_html=True)
        
        # ── Upcoming Matches ──
        if upcoming:
            st.subheader("🔜 Upcoming Rounds")
            for m in upcoming:
                with st.container(border=True):
                    st.markdown(f"**Round {m['round_num']}**")
                    st.caption(f"Accessible on: `{_format_dt(m['start_time'])}`")
                    st.markdown("*Opponent details hidden until match begins.*")
            st.markdown("<hr style='opacity: 0.2'>", unsafe_allow_html=True)
            
        # ── Completed Matches ──
        st.subheader("✅ Completed & Expired Rounds")
        if not completed:
            st.info("You have no completed rounds.")
        else:
            for m in completed:
                with st.expander(f"Round {m['round_num']} — {m['status'].capitalize()}"):
                    opp = m["player2"] if m["player1"] == name else m["player1"]
                    if opp == BYE_PLAYER:
                        st.write("BYE Round (Auto-win)")
                    else:
                        st.write(f"Opponent: **{opp}**")
                        res = get_player_result(m["match_id"], name)
                        if res:
                            st.write(f"Your report: `{res['result']}`")
                        else:
                            st.write("No result reported.")


def _render_match_panel(player: str, match: dict) -> None:
    """Show opponent details, result entry, and status for the active match."""
    opponent = match["player2"] if match["player1"] == player else match["player1"]
    
    if opponent == BYE_PLAYER:
        st.warning(
            "⏭️ **BYE ROUND**\n\n"
            "You have no opponent this round. You will automatically receive a win when this round ends. Sit back and relax!"
        )
        return

    deadline_fmt = _format_dt(match["deadline"])

    # Opponent info
    opp_data = get_user(opponent)
    opp_phone = opp_data["phone"] if opp_data else "—"

    col1, col2 = st.columns(2)
    col1.metric("Opponent", opponent)
    col2.metric("Phone", opp_phone)

    st.caption(f"⏰ Round deadline: **{deadline_fmt}**")

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
