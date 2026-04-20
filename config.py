# =============================================================================
# Chess League Management — Central Configuration
# Adjust all values here without touching any other file.
# =============================================================================

# ── League Configuration ──────────────────────────────────────────────────────
# Index 0  = top league, index -1 = bottom league
LEAGUE_COUNT: int = 3
LEAGUE_NAMES: list[str] = ["Liga A", "Liga B", "Liga C"]

# ── Season Configuration ──────────────────────────────────────────────────────
SEASON_DURATION_HOURS: int = 72          # Total season length in hours

# ── Points ────────────────────────────────────────────────────────────────────
POINTS_WIN: int  = 3
POINTS_DRAW: int = 1
POINTS_LOSS: int = 0

# ── Promotion / Relegation ────────────────────────────────────────────────────
# Number of players promoted AND relegated between adjacent leagues each season
PROMOTION_RELEGATION_COUNT: int = 2

# ── Internals (do not change unless you know what you are doing) ──────────────
BYE_PLAYER: str = "BYE"                 # Virtual player for odd-sized leagues
ADMIN_USERNAME: str = "admin"           # Admin login name (password via secrets)
SEASON_ROW_ID: int = 1                  # Single-row id in the seasons table
