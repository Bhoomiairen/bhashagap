"""Load collected rows into DuckDB and build the metric views (metrics.sql)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .config import Language

SCHEMA = """
CREATE TABLE languages (code VARCHAR PRIMARY KEY, name VARCHAR, native_name VARCHAR, script VARCHAR,
                        speakers_millions DOUBLE, bytes_per_char INTEGER);
CREATE TABLE topics (qid VARCHAR PRIMARY KEY, en_title VARCHAR, en_length INTEGER, en_last_edit TIMESTAMP, en_chars INTEGER);
CREATE TABLE topic_categories (qid VARCHAR, category VARCHAR);
CREATE TABLE articles (qid VARCHAR, lang VARCHAR, title VARCHAR, length_bytes INTEGER, last_edit TIMESTAMP, text_chars INTEGER);
CREATE TABLE pageviews (qid VARCHAR, lang VARCHAR, views BIGINT);
CREATE TABLE meta (key VARCHAR PRIMARY KEY, value VARCHAR);
"""


def _ts(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)


def build(db_path: Path, languages: list[Language], topics: dict, topic_categories, article_rows, pageview_rows,
          meta: dict) -> duckdb.DuckDBPyConnection:
    """Create a fresh database file from collected rows. Returns an open connection."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    con.execute(SCHEMA)
    con.executemany("INSERT INTO languages VALUES (?, ?, ?, ?, ?, ?)",
                    [(l.code, l.name, l.native_name, l.script, l.speakers_millions, l.bytes_per_char) for l in languages])
    con.executemany("INSERT INTO topics VALUES (?, ?, ?, ?, ?)",
                    [(t["qid"], t["en_title"], t["en_length"], _ts(t["en_last_edit"]), t.get("en_chars")) for t in topics.values()])
    con.executemany("INSERT INTO topic_categories VALUES (?, ?)", list(topic_categories))
    if article_rows:
        # rows: (qid, lang, title, length_bytes, last_edit[, text_chars])
        con.executemany("INSERT INTO articles VALUES (?, ?, ?, ?, ?, ?)",
                        [(r[0], r[1], r[2], r[3], _ts(r[4]), r[5] if len(r) > 5 else None) for r in article_rows])
    if pageview_rows:
        con.executemany("INSERT INTO pageviews VALUES (?, ?, ?)", list(pageview_rows))
    meta = {"run_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"), **meta}
    con.executemany("INSERT INTO meta VALUES (?, ?)", [(k, str(v)) for k, v in meta.items()])
    create_views(con)
    return con


def create_views(con):
    con.execute((Path(__file__).parent / "metrics.sql").read_text("utf-8"))
