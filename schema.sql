-- TSA security wait times: one row per checkpoint (terminal × optional gate × queue) per scrape
CREATE TABLE IF NOT EXISTS wait_times (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scraped_at_utc TEXT NOT NULL,
    airport TEXT NOT NULL,
    terminal TEXT NOT NULL,
    gate TEXT NOT NULL DEFAULT '',
    queue_type TEXT NOT NULL,
    wait_minutes INTEGER,
    wait_min_minutes INTEGER,
    wait_max_minutes INTEGER,
    source_updated_at TEXT,
    point_id INTEGER,
    UNIQUE(scraped_at_utc, airport, terminal, queue_type, gate)
);

CREATE INDEX IF NOT EXISTS idx_wait_times_scraped ON wait_times(scraped_at_utc);
CREATE INDEX IF NOT EXISTS idx_wait_times_airport_terminal ON wait_times(airport, terminal);

-- Per-airport fetch+store timing for each scraper run (aligned with wait_times.scraped_at_utc)
CREATE TABLE IF NOT EXISTS scrape_airport_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scraped_at_utc TEXT NOT NULL,
    airport TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    ok INTEGER NOT NULL,
    error TEXT,
    UNIQUE(scraped_at_utc, airport)
);

CREATE INDEX IF NOT EXISTS idx_scrape_airport_stats_scraped ON scrape_airport_stats(scraped_at_utc);

-- Actual X posts, one row per terminal/chart target included in a post.
-- Grouped airport alerts share the same tweet_id.
CREATE TABLE IF NOT EXISTS tweet_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    airport TEXT NOT NULL,
    terminal TEXT NOT NULL,
    gate TEXT NOT NULL DEFAULT '',
    threshold_minutes INTEGER NOT NULL,
    wait_minutes INTEGER NOT NULL,
    tweet_text TEXT NOT NULL,
    tweet_url TEXT NOT NULL,
    tweet_id TEXT NOT NULL,
    alerted_at_utc TEXT NOT NULL,
    scraped_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tweet_alerts_target_time
ON tweet_alerts(airport, terminal, gate, alerted_at_utc);
