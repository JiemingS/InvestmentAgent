from ..db import migrate

RESEARCH_MIGRATIONS = (
    (
        """
        CREATE TABLE economic_events (
            id TEXT PRIMARY KEY,
            agency TEXT NOT NULL,
            event_type TEXT NOT NULL,
            title TEXT NOT NULL,
            event_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            display_date TEXT NOT NULL,
            display_end TEXT NOT NULL,
            scheduled_at_utc TEXT,
            timezone TEXT NOT NULL,
            original_time TEXT,
            source_url TEXT NOT NULL,
            status TEXT NOT NULL,
            provider_id TEXT,
            sequence INTEGER,
            provider_updated_at TEXT,
            last_verified_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX events_by_date ON economic_events(agency, display_date, display_end)",
        "CREATE INDEX events_by_provider_id ON economic_events(agency, provider_id)",
        """
        CREATE TABLE calendar_sync (
            agency TEXT PRIMARY KEY,
            last_attempt_at TEXT,
            last_success_at TEXT,
            last_import_at TEXT,
            status TEXT NOT NULL,
            error_message TEXT
        )
        """,
        """
        CREATE TABLE articles (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            publisher TEXT NOT NULL,
            published_at TEXT,
            published_date TEXT,
            retrieved_at TEXT NOT NULL,
            evidence TEXT NOT NULL,
            fetched_at TEXT,
            fetched_url TEXT,
            page_excerpt TEXT
        )
        """,
        """
        CREATE TABLE searches (
            query_key TEXT NOT NULL,
            days INTEGER NOT NULL,
            query TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            article_ids TEXT NOT NULL,
            PRIMARY KEY (query_key, days)
        )
        """,
    ),
    (
        """
        CREATE TABLE saved_articles (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            publisher TEXT NOT NULL,
            published_at TEXT,
            published_date TEXT,
            saved_at TEXT NOT NULL,
            summary TEXT NOT NULL
        )
        """,
    ),
)


def migrate_research(path):
    migrate(path, RESEARCH_MIGRATIONS)
