-- TSA security wait times: one row per terminal × queue type per scrape
CREATE TABLE IF NOT EXISTS wait_times (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scraped_at_utc TEXT NOT NULL,
    airport TEXT NOT NULL,
    terminal TEXT NOT NULL,
    queue_type TEXT NOT NULL,
    wait_minutes INTEGER NOT NULL,
    source_updated_at TEXT,
    point_id INTEGER,
    UNIQUE(scraped_at_utc, airport, terminal, queue_type)
);

CREATE INDEX IF NOT EXISTS idx_wait_times_scraped ON wait_times(scraped_at_utc);
CREATE INDEX IF NOT EXISTS idx_wait_times_airport_terminal ON wait_times(airport, terminal);
