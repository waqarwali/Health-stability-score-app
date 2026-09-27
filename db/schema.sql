PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id          INTEGER  PRIMARY KEY AUTOINCREMENT,
    name             TEXT     NOT NULL,
    email            TEXT     NOT NULL UNIQUE,
    timezone         TEXT     NOT NULL DEFAULT 'UTC',
    target_sleep_hr  REAL     NOT NULL DEFAULT 8.0,
    target_water_ml  INTEGER  NOT NULL DEFAULT 2500,
    target_steps     INTEGER  NOT NULL DEFAULT 8000,
    created_at       TIMESTAMP         DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS daily_logs (
    log_id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER  NOT NULL
                                 REFERENCES users(user_id) ON DELETE CASCADE,
    log_date            DATE     NOT NULL,
    sleep_start         TEXT,
    sleep_end           TEXT,
    wake_time           TEXT,
    sleep_duration_hr   REAL,
    meal_times          TEXT,                        -- JSON array of HH:MM strings
    steps               INTEGER  NOT NULL DEFAULT 0,
    water_ml            INTEGER  NOT NULL DEFAULT 0,
    screen_min          INTEGER  NOT NULL DEFAULT 0,
    mood_score          INTEGER  CHECK (mood_score BETWEEN 1 AND 10),
    energy_score        INTEGER  CHECK (energy_score BETWEEN 1 AND 10),
    productivity_score  INTEGER  CHECK (productivity_score BETWEEN 1 AND 10),
    notes               TEXT,
    created_at          TIMESTAMP         DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, log_date)
);

-- Indexes on daily_logs
CREATE INDEX IF NOT EXISTS idx_daily_logs_user_id
    ON daily_logs (user_id);

CREATE INDEX IF NOT EXISTS idx_daily_logs_log_date
    ON daily_logs (log_date);


CREATE TABLE IF NOT EXISTS habit_scores (
    score_id      INTEGER  PRIMARY KEY AUTOINCREMENT,
    log_id        INTEGER  NOT NULL
                           REFERENCES daily_logs(log_id) ON DELETE CASCADE,
    user_id       INTEGER  NOT NULL
                           REFERENCES users(user_id)     ON DELETE CASCADE,
    habit_type    TEXT     NOT NULL,                 -- 'sleep' | 'meal_timing' | 'activity' | 'hydration' | 'screen_time'
    raw_value     REAL,
    seven_day_mean REAL,
    seven_day_std  REAL,
    deviation      REAL,
    stability_pct  REAL    CHECK (stability_pct BETWEEN 0 AND 100),
    is_disrupted   INTEGER NOT NULL DEFAULT 0,       -- 0 = false, 1 = true
    computed_at    TIMESTAMP        DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS stability_scores (
    id             INTEGER  PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER  NOT NULL
                            REFERENCES users(user_id) ON DELETE CASCADE,
    score_date     DATE     NOT NULL,
    period_type    TEXT     NOT NULL CHECK (period_type IN ('daily', 'weekly')),
    overall_score  REAL,
    sleep_score    REAL,
    meal_score     REAL,
    activity_score REAL,
    hydration_score REAL,
    screen_score   REAL,
    created_at     TIMESTAMP         DEFAULT CURRENT_TIMESTAMP
);

-- Composite index on stability_scores
CREATE INDEX IF NOT EXISTS idx_stability_scores_user_date
    ON stability_scores (user_id, score_date);

CREATE TABLE IF NOT EXISTS disruptions (
    id           INTEGER  PRIMARY KEY AUTOINCREMENT,
    log_id       INTEGER  NOT NULL
                          REFERENCES daily_logs(log_id) ON DELETE CASCADE,
    user_id      INTEGER  NOT NULL
                          REFERENCES users(user_id)     ON DELETE CASCADE,
    habit_type   TEXT     NOT NULL,
    severity     TEXT     NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
    description  TEXT,
    detected_at  TIMESTAMP         DEFAULT CURRENT_TIMESTAMP
);



CREATE TABLE IF NOT EXISTS suggestions (
    id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER  NOT NULL
                             REFERENCES users(user_id) ON DELETE CASCADE,
    week_of         DATE,
    habit_type      TEXT,
    suggestion_text TEXT,
    priority        INTEGER  NOT NULL DEFAULT 1,
    is_shown        INTEGER  NOT NULL DEFAULT 0,     -- 0 = not shown, 1 = shown
    created_at      TIMESTAMP         DEFAULT CURRENT_TIMESTAMP
);
