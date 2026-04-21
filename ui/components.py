"""
ui/components.py — Shared Streamlit UI components.
"""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from db import get_standings


# ── Leaderboard ───────────────────────────────────────────────────────────────

def render_leaderboard(league: str, highlight: str | None = None) -> None:
    """
    Render a styled standings table for the given league.
    highlight: player name to visually emphasise (the logged-in user).
    """
    rows = get_standings(league)
    if not rows:
        st.info("No players in this league yet.")
        return

    st.markdown(f"#### 🏆 {league} Standings")

    header_cols = st.columns([1, 4, 3, 3])
    header_cols[0].markdown("**#**")
    header_cols[1].markdown("**Player**")
    header_cols[2].markdown("**Points**")
    header_cols[3].markdown("**League**")

    st.divider()

    for p in rows:
        is_me = p["name"] == highlight
        cols = st.columns([1, 4, 3, 3])
        rank_str = f"**{p['rank']}**"
        name_str = f"**{p['name']} ← you**" if is_me else p["name"]

        cols[0].markdown(rank_str)
        cols[1].markdown(name_str)
        cols[2].markdown(f"`{p['points']} pts`")
        cols[3].markdown(p["league"])


# ── Countdown ─────────────────────────────────────────────────────────────────

def render_countdown(season_end_iso: str) -> None:
    """Display a live HH:MM:SS countdown to the season end."""
    try:
        end_dt = datetime.fromisoformat(season_end_iso)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        st.warning("Invalid season end time.")
        return

    now = datetime.now(timezone.utc)
    delta = end_dt - now

    if delta.total_seconds() <= 0:
        st.error("⏰ Season has ended — awaiting reset.")
        return

    total_secs = int(delta.total_seconds())
    hours, rem = divmod(total_secs, 3600)
    minutes, seconds = divmod(rem, 60)

    st.markdown(
        f"""
        <div style='text-align:center; padding:6px 0 10px 0'>
            <span style='font-size:0.75rem; color:#aaa; letter-spacing:1px'>
                SEASON ENDS IN
            </span><br>
            <span style='font-size:2rem; font-weight:700; font-family:monospace;
                         color:#f0c040'>
                {hours:02d}:{minutes:02d}:{seconds:02d}
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
