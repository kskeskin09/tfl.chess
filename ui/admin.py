"""
ui/admin.py — Admin dashboard page (password-protected).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

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
    get_all_matches,
    get_all_users,
    get_standings,
    get_season,
    insert_matches,
    reset_all_points,
    set_user_league,
    upsert_season,
    update_match_status,
    upsert_result,
    update_user_points,
)
from scheduler import distribute_players, generate_fixtures
from ui.components import render_countdown, render_leaderboard


# ── Entry point ───────────────────────────────────────────────────────────────

def render_admin() -> None:
    st.markdown("## 🛡️ Admin Dashboard")
    st.caption("Full visibility and control over the Chess League system.")

    season = get_season()

    # ── Top metrics ───────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    users = get_all_users()
    matches = get_all_matches()
    disputes = [m for m in matches if m["status"] == "disputed"]
    completed = [m for m in matches if m["status"] == "completed"]

    col1.metric("👥 Total Players", len(users))
    col2.metric("🎮 Total Matches", len(matches))
    col3.metric("✅ Completed", len(completed))
    col4.metric("⚠️ Disputed", len(disputes))

    st.divider()

    # ── Season control ────────────────────────────────────────────────────────
    st.subheader("⚙️ Season Control")

    if season:
        is_active = season.get("active", False)
        end_iso = season.get("season_end", "")
        start_iso = season.get("season_start", "")
        season_num = season.get("season_number", 1)

        try:
            end_dt = datetime.fromisoformat(end_iso)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            start_dt = datetime.fromisoformat(start_iso)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)

            fmt = "%d %b %Y  %H:%M UTC"
            st.info(
                f"**Season #{season_num}** &nbsp;|&nbsp; "
                f"Start: `{start_dt.strftime(fmt)}` &nbsp;→&nbsp; "
                f"End: `{end_dt.strftime(fmt)}` &nbsp;|&nbsp; "
                f"Status: {'🟢 Active' if is_active else '🔴 Inactive'}"
            )
            if is_active:
                render_countdown(end_iso)
        except Exception:
            st.warning("Season record found but timestamps are invalid.")
    else:
        st.warning("No season exists yet. Start one below.")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("🚀 Start New Season", use_container_width=True, type="primary"):
            _start_new_season()
    with c2:
        if st.button("🏁 End Season Now", use_container_width=True):
            _end_season()

    st.divider()

    # ── League standings ──────────────────────────────────────────────────────
    st.subheader("📊 All League Standings")
    tab_objects = st.tabs(LEAGUE_NAMES)
    for tab, lg in zip(tab_objects, LEAGUE_NAMES):
        with tab:
            render_leaderboard(lg)

    st.divider()

    # ── All fixtures ──────────────────────────────────────────────────────────
    st.subheader("📅 All Fixtures")
    _render_all_fixtures(matches)

    st.divider()

    # ── Disputes ──────────────────────────────────────────────────────────────
    if disputes:
        st.subheader("⚠️ Disputed Matches — Manual Override")
        _render_disputes(disputes)

    st.divider()

    # ── Player management ─────────────────────────────────────────────────────
    st.subheader("👥 Player Management")
    _render_player_management(users)

    st.divider()

    # ── Password hash utility ─────────────────────────────────────────────────
    st.subheader("🔑 Password Hash Generator")
    st.caption("Use this to generate bcrypt hashes when adding users to Supabase.")
    raw_pw = st.text_input("Plaintext password", type="password", key="hash_input")
    if st.button("Generate Hash", key="gen_hash"):
        from auth import hash_password
        st.code(hash_password(raw_pw), language=None)


# ── Season actions ────────────────────────────────────────────────────────────

def _start_new_season() -> None:
    """
    1. Apply promotion/relegation (if a previous season exists).
    2. Reset points.
    3. Clear old matches/results.
    4. Distribute players and generate new fixtures.
    5. Write new season row.
    """
    with st.spinner("Starting new season…"):
        existing = get_season()
        if existing and existing.get("active"):
            # Finalise before restarting
            auto_complete_bye_matches()
            apply_promotion_relegation(LEAGUE_NAMES, PROMOTION_RELEGATION_COUNT)

        reset_all_points()
        clear_results()
        clear_matches()

        now = datetime.now(timezone.utc)
        season_end = now + timedelta(hours=SEASON_DURATION_HOURS)

        # Re-read users after promotion/relegation
        all_users = get_all_users()
        # Group by current league
        league_players: dict[str, list[str]] = {lg: [] for lg in LEAGUE_NAMES}
        for u in all_users:
            if u["league"] in league_players:
                league_players[u["league"]].append(u["name"])

        all_rows: list[dict] = []
        for idx, lg in enumerate(LEAGUE_NAMES):
            players = league_players.get(lg, [])
            if len(players) < 2:
                continue
            rows = generate_fixtures(lg, idx, players, now, season_end)
            all_rows.extend(rows)

        if all_rows:
            insert_matches(all_rows)

        prev_num = existing.get("season_number", 0) if existing else 0
        upsert_season(
            {
                "season_number": prev_num + 1,
                "season_start": now.isoformat(),
                "season_end": season_end.isoformat(),
                "active": True,
            }
        )

    st.success(f"✅ Season #{prev_num + 1} started! {len(all_rows)} matches generated.")
    st.rerun()


def _end_season() -> None:
    """Finalise BYEs, apply promotion/relegation, reset, and start next season."""
    with st.spinner("Ending season and computing results…"):
        auto_complete_bye_matches()
        apply_promotion_relegation(LEAGUE_NAMES, PROMOTION_RELEGATION_COUNT)

    st.success("Season ended. Promotion/relegation applied.")
    _start_new_season()


# ── Fixtures table ────────────────────────────────────────────────────────────

def _render_all_fixtures(matches: list[dict]) -> None:
    if not matches:
        st.info("No fixtures generated yet.")
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    rows = []
    for m in sorted(matches, key=lambda x: x["start_time"]):
        if m["start_time"] <= now_iso <= m["deadline"]:
            timing = "🟢 Active"
        elif now_iso < m["start_time"]:
            timing = "🔵 Upcoming"
        else:
            timing = "⚫ Past"

        rows.append(
            {
                "League": m["league"],
                "Match ID": m["match_id"],
                "Player 1": m["player1"],
                "Player 2": m["player2"],
                "Timing": timing,
                "Status": m["status"],
                "Deadline": m["deadline"][:16].replace("T", " "),
            }
        )

    st.dataframe(rows, use_container_width=True, hide_index=True)


# ── Dispute resolution ────────────────────────────────────────────────────────

def _render_disputes(disputes: list[dict]) -> None:
    for m in disputes:
        with st.expander(f"⚠️ {m['match_id']}  —  {m['player1']} vs {m['player2']}"):
            st.write(f"**League:** {m['league']}")
            from db import get_results_for_match
            results = get_results_for_match(m["match_id"])
            for r in results:
                st.write(f"• **{r['result_player']}** reported: `{r['result']}`")

            st.markdown("**Admin override — set the correct result:**")
            winner_opts = [m["player1"], m["player2"], "Draw"]
            winner = st.selectbox(
                "Winner / outcome", winner_opts, key=f"disp_{m['match_id']}"
            )
            if st.button("✅ Apply Override", key=f"apply_{m['match_id']}"):
                _apply_dispute_override(m, winner)
                st.success("Override applied.")
                st.rerun()


def _apply_dispute_override(match: dict, winner: str) -> None:
    p1, p2 = match["player1"], match["player2"]
    if winner == "Draw":
        upsert_result(match["match_id"], p1, "Draw")
        upsert_result(match["match_id"], p2, "Draw")
        update_user_points(p1, 1)
        update_user_points(p2, 1)
    else:
        loser = p2 if winner == p1 else p1
        upsert_result(match["match_id"], winner, "Win")
        upsert_result(match["match_id"], loser, "Loss")
        update_user_points(winner, 3)
    update_match_status(match["match_id"], "completed")


# ── Player management ──────────────────────────────────────────────────────────

def _render_player_management(users: list[dict]) -> None:
    if not users:
        st.info("No players in the database.")
        return

    rows = [
        {
            "Name": u["name"],
            "League": u["league"],
            "Points": u["points"],
            "Phone": u.get("phone", "—"),
        }
        for u in sorted(users, key=lambda u: (u["league"], -u["points"]))
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    st.markdown("**Move player to a different league:**")
    col1, col2, col3 = st.columns(3)
    with col1:
        target_player = st.selectbox(
            "Player", [u["name"] for u in users], key="mv_player"
        )
    with col2:
        target_league = st.selectbox("New League", LEAGUE_NAMES, key="mv_league")
    with col3:
        st.write("")
        st.write("")
        if st.button("Move", key="mv_btn"):
            set_user_league(target_player, target_league)
            st.success(f"Moved **{target_player}** → **{target_league}**")
            st.rerun()
