"""
db.py — All Supabase database operations for the Chess League app.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import streamlit as st
from postgrest.exceptions import APIError
from supabase import Client, create_client

from config import POINTS_DRAW, POINTS_WIN, SEASON_ROW_ID


def _db_error(exc: Exception) -> None:
    """Show a clear, actionable error and stop execution."""
    st.error(
        "⚠️ **Database error** — could not reach Supabase.\n\n"
        "**Possible causes:**\n"
        "1. `SUPABASE_URL` / `SUPABASE_KEY` not set in Streamlit Cloud secrets.\n"
        "2. Row-Level Security (RLS) is **enabled** on your tables — "
        "run the RLS-disable statements in `setup.sql` or use the **service role** key.\n"
        "3. The `setup.sql` schema has not been executed yet.\n\n"
        f"Raw error: `{exc}`"
    )
    st.stop()


# ── Client ────────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def get_client() -> Client:
    """Return a cached Supabase client using st.secrets credentials."""
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


# ── Season ────────────────────────────────────────────────────────────────────

def get_season() -> Optional[dict]:
    try:
        res = get_client().table("seasons").select("*").eq("id", SEASON_ROW_ID).execute()
        return res.data[0] if res.data else None
    except (APIError, Exception) as exc:
        _db_error(exc)


def upsert_season(data: dict) -> None:
    data["id"] = SEASON_ROW_ID
    get_client().table("seasons").upsert(data).execute()


def set_season_inactive() -> None:
    get_client().table("seasons").update({"active": False}).eq("id", SEASON_ROW_ID).execute()


# ── Users ─────────────────────────────────────────────────────────────────────

def get_user(name: str) -> Optional[dict]:
    res = get_client().table("users").select("*").eq("name", name).execute()
    return res.data[0] if res.data else None


def get_all_users() -> list[dict]:
    return get_client().table("users").select("*").execute().data


def get_users_by_league(league: str) -> list[dict]:
    return (
        get_client().table("users").select("*").eq("league", league).execute().data
    )


def update_user_points(name: str, delta: int) -> None:
    user = get_user(name)
    if user:
        new_pts = user["points"] + delta
        get_client().table("users").update({"points": new_pts}).eq("name", name).execute()


def set_user_points(name: str, points: int) -> None:
    get_client().table("users").update({"points": points}).eq("name", name).execute()


def set_user_league(name: str, league: str) -> None:
    get_client().table("users").update({"league": league}).eq("name", name).execute()


def reset_all_points() -> None:
    """Set every player's points back to 0."""
    users = get_all_users()
    for u in users:
        set_user_points(u["name"], 0)


# ── Matches ───────────────────────────────────────────────────────────────────

def get_all_matches() -> list[dict]:
    return get_client().table("matches").select("*").execute().data


def get_matches_by_league(league: str) -> list[dict]:
    return (
        get_client().table("matches").select("*").eq("league", league).execute().data
    )


def get_match(match_id: str) -> Optional[dict]:
    res = get_client().table("matches").select("*").eq("match_id", match_id).execute()
    return res.data[0] if res.data else None


def get_player_matches(player: str) -> list[dict]:
    sb = get_client()
    r1 = sb.table("matches").select("*").eq("player1", player).execute().data
    r2 = sb.table("matches").select("*").eq("player2", player).execute().data
    return r1 + r2


def get_current_match(player: str) -> Optional[dict]:
    """Return the match whose time window contains right now."""
    now = datetime.now(timezone.utc).isoformat()
    matches = get_player_matches(player)
    for m in matches:
        if m["start_time"] <= now <= m["deadline"]:
            return m
    return None


def get_match_between(p1: str, p2: str) -> Optional[dict]:
    sb = get_client()
    r = sb.table("matches").select("*").eq("player1", p1).eq("player2", p2).execute().data
    if r:
        return r[0]
    r = sb.table("matches").select("*").eq("player1", p2).eq("player2", p1).execute().data
    return r[0] if r else None


def insert_matches(rows: list[dict]) -> None:
    if rows:
        get_client().table("matches").insert(rows).execute()


def update_match_status(match_id: str, status: str) -> None:
    get_client().table("matches").update({"status": status}).eq("match_id", match_id).execute()


def clear_matches() -> None:
    get_client().table("matches").delete().neq("match_id", "").execute()


# ── Results ───────────────────────────────────────────────────────────────────

def get_results_for_match(match_id: str) -> list[dict]:
    return (
        get_client().table("results").select("*").eq("match_id", match_id).execute().data
    )


def get_player_result(match_id: str, player: str) -> Optional[dict]:
    res = (
        get_client()
        .table("results")
        .select("*")
        .eq("match_id", match_id)
        .eq("result_player", player)
        .execute()
    )
    return res.data[0] if res.data else None


def upsert_result(match_id: str, player: str, result: str) -> None:
    get_client().table("results").upsert(
        {"match_id": match_id, "result_player": player, "result": result}
    ).execute()


def clear_results() -> None:
    get_client().table("results").delete().neq("match_id", "").execute()


# ── Result verification & point awarding ──────────────────────────────────────

_OPPOSITE = {"Win": "Loss", "Loss": "Win", "Draw": "Draw"}


def check_and_finalize_match(match_id: str) -> str:
    """
    After a result is submitted, check if both sides agree.
    Returns: 'finalized' | 'disputed' | 'waiting' | 'already_done'
    """
    match = get_match(match_id)
    if not match or match["status"] in ("completed", "bye"):
        return "already_done"

    results = get_results_for_match(match_id)
    if len(results) < 2:
        return "waiting"

    r_map = {r["result_player"]: r["result"] for r in results}
    p1, p2 = match["player1"], match["player2"]
    r1 = r_map.get(p1)
    r2 = r_map.get(p2)

    if not r1 or not r2:
        return "waiting"

    if _OPPOSITE[r1] == r2:
        # Results match — award points
        _award_points(p1, r1)
        _award_points(p2, r2)
        update_match_status(match_id, "completed")
        return "finalized"
    else:
        update_match_status(match_id, "disputed")
        return "disputed"


def _award_points(player: str, result: str) -> None:
    if result == "Win":
        update_user_points(player, POINTS_WIN)
    elif result == "Draw":
        update_user_points(player, POINTS_DRAW)
    # Loss: 0 points


def auto_complete_bye_matches() -> None:
    """Award wins for all pending BYE matches whose deadline has passed."""
    now = datetime.now(timezone.utc).isoformat()
    matches = get_all_matches()
    for m in matches:
        if m["status"] == "bye" and m["deadline"] < now:
            real_player = m["player1"]  # BYE is always stored as player2
            update_user_points(real_player, POINTS_WIN)
            update_match_status(m["match_id"], "completed")


# ── Standings with H2H tiebreaker ─────────────────────────────────────────────

def get_standings(league: str) -> list[dict]:
    """
    Return sorted leaderboard for a league.
    Primary sort: points DESC.
    Tiebreaker: Head-to-Head points among tied players.
    """
    players = get_users_by_league(league)
    if not players:
        return []

    # Group by points
    from collections import defaultdict
    groups: dict[int, list[dict]] = defaultdict(list)
    for p in players:
        groups[p["points"]].append(p)

    sorted_players: list[dict] = []
    for pts in sorted(groups.keys(), reverse=True):
        group = groups[pts]
        if len(group) == 1:
            sorted_players.extend(group)
        else:
            sorted_players.extend(_h2h_sort(group))

    for rank, p in enumerate(sorted_players, 1):
        p["rank"] = rank
    return sorted_players


def _h2h_sort(players: list[dict]) -> list[dict]:
    """Sort a group of tied players by head-to-head record."""
    names = [p["name"] for p in players]
    h2h: dict[str, int] = {n: 0 for n in names}

    for i, n1 in enumerate(names):
        for n2 in names[i + 1 :]:
            match = get_match_between(n1, n2)
            if not match or match["status"] != "completed":
                continue
            results = get_results_for_match(match["match_id"])
            r_map = {r["result_player"]: r["result"] for r in results}
            if r_map.get(n1) == "Win":
                h2h[n1] += POINTS_WIN
            elif r_map.get(n1) == "Draw":
                h2h[n1] += POINTS_DRAW
                h2h[n2] += POINTS_DRAW
            elif r_map.get(n1) == "Loss":
                h2h[n2] += POINTS_WIN

    player_map = {p["name"]: p for p in players}
    return sorted(players, key=lambda p: h2h[p["name"]], reverse=True)


# ── Promotion / Relegation ────────────────────────────────────────────────────

def apply_promotion_relegation(league_names: list[str], count: int) -> None:
    """
    Promote top `count` from lower leagues → higher league.
    Relegate bottom `count` from higher leagues → lower league.
    """
    standings: list[list[dict]] = [get_standings(lg) for lg in league_names]

    for i in range(len(league_names) - 1):
        higher = league_names[i]
        lower = league_names[i + 1]
        upper_table = standings[i]
        lower_table = standings[i + 1]

        # Bottom of higher → lower
        relegated = upper_table[-count:] if len(upper_table) >= count else upper_table
        for p in relegated:
            set_user_league(p["name"], lower)

        # Top of lower → higher
        promoted = lower_table[:count] if len(lower_table) >= count else lower_table
        for p in promoted:
            set_user_league(p["name"], higher)
