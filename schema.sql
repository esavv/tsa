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
