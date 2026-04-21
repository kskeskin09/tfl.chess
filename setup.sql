-- ============================================================
-- Chess League Management — Supabase Database Setup
-- Run this in the Supabase SQL Editor once to create all tables.
-- ============================================================

-- 1. Season metadata (always a single row with id = 1)
CREATE TABLE IF NOT EXISTS seasons (
    id            INTEGER      PRIMARY KEY DEFAULT 1,
    season_number INTEGER      NOT NULL    DEFAULT 1,
    season_start  TIMESTAMPTZ  NOT NULL,
    season_end    TIMESTAMPTZ  NOT NULL,
    active        BOOLEAN      NOT NULL    DEFAULT TRUE
);

-- 2. Players
CREATE TABLE IF NOT EXISTS users (
    name     TEXT    PRIMARY KEY,
    password TEXT    NOT NULL,          -- bcrypt hashed
    phone    TEXT,
    points   INTEGER NOT NULL DEFAULT 0,
    league   TEXT    NOT NULL
);

-- 3. Matches
CREATE TABLE IF NOT EXISTS matches (
    match_id   TEXT        PRIMARY KEY,
    player1    TEXT        NOT NULL,
    player2    TEXT        NOT NULL,    -- may be 'BYE'
    league     TEXT        NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    deadline   TIMESTAMPTZ NOT NULL,
    status     TEXT        NOT NULL DEFAULT 'pending'
    -- status values: pending | completed | disputed | bye
);

-- 4. Per-player match results
CREATE TABLE IF NOT EXISTS results (
    match_id      TEXT NOT NULL,
    result_player TEXT NOT NULL,
    result        TEXT NOT NULL,        -- Win | Loss | Draw
    PRIMARY KEY (match_id, result_player)
);

-- ============================================================
-- Row-Level Security: DISABLED on all tables.
-- Supabase enables RLS by default; without disabling it the
-- anon key cannot read/write and you'll get APIError crashes.
-- ============================================================
ALTER TABLE seasons DISABLE ROW LEVEL SECURITY;
ALTER TABLE users   DISABLE ROW LEVEL SECURITY;
ALTER TABLE matches DISABLE ROW LEVEL SECURITY;
ALTER TABLE results DISABLE ROW LEVEL SECURITY;

-- ============================================================
-- Add a test user (password = "test1234" bcrypt-hashed).
-- Generate your own hashes with: python -c "import bcrypt; print(bcrypt.hashpw(b'yourpass', bcrypt.gensalt()).decode())"
-- ============================================================
-- INSERT INTO users (name, password, phone, points, league)
-- VALUES ('Alice', '$2b$12$...', '+905001234567', 0, 'Liga A');
