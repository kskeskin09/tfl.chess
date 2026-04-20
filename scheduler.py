"""
scheduler.py — Round-robin fixture generator using the Circle Algorithm.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from config import BYE_PLAYER


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean(name: str) -> str:
    """Strip non-alphanumeric chars for use in match_id."""
    return re.sub(r"[^a-zA-Z0-9]", "", name)


# ── Circle Algorithm ──────────────────────────────────────────────────────────

def round_robin(players: list[str]) -> list[list[tuple[str, str]]]:
    """
    Generate a round-robin schedule.
    Returns a list of rounds; each round is a list of (player1, player2) pairs.
    BYE is appended when len(players) is odd so every player gets exactly one bye.
    """
    roster = list(players)
    if len(roster) % 2 == 1:
        roster.append(BYE_PLAYER)

    n = len(roster)
    fixed = roster[0]
    rotating = roster[1:]
    rounds: list[list[tuple[str, str]]] = []

    for _ in range(n - 1):
        pairs: list[tuple[str, str]] = [(fixed, rotating[-1])]
        half = len(rotating) // 2
        for i in range(half - 1):
            pairs.append((rotating[i], rotating[-(i + 2)]))
        rounds.append(pairs)
        # Rotate: move last element to front
        rotating = [rotating[-1]] + rotating[:-1]

    return rounds


# ── Fixture Builder ───────────────────────────────────────────────────────────

def generate_fixtures(
    league_name: str,
    league_idx: int,          # 0-based index (used in match_id)
    players: list[str],
    season_start: datetime,
    season_end: datetime,
) -> list[dict]:
    """
    Build all match rows ready for insertion into the `matches` table.

    match_id format: L{n}R{r}{P1}vs{P2}
      n = league number (1-based)
      r = round number  (1-based)
    """
    if len(players) < 2:
        return []

    rounds = round_robin(players)
    total_rounds = len(rounds)
    if total_rounds == 0:
        return []

    total_seconds = (season_end - season_start).total_seconds()
    round_secs = total_seconds / total_rounds

    rows: list[dict] = []
    for r_idx, pairs in enumerate(rounds):
        r_start = season_start + timedelta(seconds=r_idx * round_secs)
        r_end   = season_start + timedelta(seconds=(r_idx + 1) * round_secs)

        for p1, p2 in pairs:
            # BYE is always player2 for consistency
            if p1 == BYE_PLAYER:
                p1, p2 = p2, p1

            is_bye = p2 == BYE_PLAYER
            mid = f"L{league_idx+1}R{r_idx+1}{_clean(p1)}vs{_clean(p2)}"

            rows.append(
                {
                    "match_id":   mid,
                    "player1":    p1,
                    "player2":    p2,
                    "league":     league_name,
                    "start_time": r_start.isoformat(),
                    "deadline":   r_end.isoformat(),
                    "status":     "bye" if is_bye else "pending",
                }
            )

    return rows


# ── Player distribution ───────────────────────────────────────────────────────

def distribute_players(
    players: list[str],
    league_names: list[str],
) -> dict[str, list[str]]:
    """
    Distribute players equally across leagues.
    Remainder players go one-by-one to the LOWEST leagues first.

    Returns {league_name: [player, ...]}
    """
    n = len(players)
    k = len(league_names)
    base, remainder = divmod(n, k)

    assignment: dict[str, list[str]] = {lg: [] for lg in league_names}
    idx = 0
    for i, lg in enumerate(league_names):
        # Leagues at the END (lowest) of the list get the extras
        extra = 1 if i >= (k - remainder) else 0
        count = base + extra
        assignment[lg] = players[idx : idx + count]
        idx += count

    return assignment
