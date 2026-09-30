"""Write the dataset (CSV) and the website's data files (JSON) from the DuckDB database."""

from __future__ import annotations

import json
from pathlib import Path

from .config import CATEGORY_LABELS

STATUS_CODE = {"stub": 1, "partial": 2, "good": 3}  # missing = absent from the JSON


def _r(x, nd=3):
    return None if x is None else round(float(x), nd)


def export_csv(con, out_dir: Path):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    queries = {
        "language_scores.csv": "SELECT * EXCLUDE (script) FROM language_scores ORDER BY access_score DESC",
        "category_scores.csv": "SELECT * FROM category_scores ORDER BY lang, category",
        "coverage.csv": "SELECT qid, en_title, lang, status, title, text_chars, en_chars, length_bytes, ROUND(depth, 3) AS depth, last_edit, en_views, lang_views FROM coverage ORDER BY qid, lang",
        "priorities.csv": "SELECT * FROM priorities ORDER BY lang, rank",
        "topics.csv": """SELECT t.qid, t.en_title, t.en_length, t.en_chars, string_agg(tc.category, ';' ORDER BY tc.category) AS categories,
                                COALESCE(p.views, 0) AS en_views_12m
                         FROM topics t JOIN topic_categories tc USING (qid)
                         LEFT JOIN pageviews p ON p.qid = t.qid AND p.lang = 'en'
                         GROUP BY ALL ORDER BY en_views_12m DESC""",
    }
    for name, sql in queries.items():
        path = out_dir / name
        con.execute(f"COPY ({sql}) TO '{path.as_posix()}' (HEADER, DELIMITER ',')")
    return list(queries)


def export_site(con, out_dir: Path):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())

    langs = con.execute("SELECT * FROM language_scores ORDER BY access_score DESC").fetchdf().to_dict("records")
    languages = [{
        "code": l["code"], "name": l["name"], "native": l["native_name"], "script": l["script"],
        "speakers": l["speakers_millions"], "topics": int(l["topics"]), "present": int(l["present"]),
        "missing": int(l["missing"]), "stubs": int(l["stubs"]), "substantial": int(l["substantial"]),
        "coverage": _r(l["coverage"]), "demandCoverage": _r(l["demand_coverage"]),
        "depth": _r(l["depth_of_present"]), "fresh": _r(l["fresh_share"]),
        "views": int(l["lang_views"] or 0), "access": _r(l["access_score"], 1),
        "speakersPerArticle": _r(l["speakers_per_article"], 0),
    } for l in langs]

    cats = con.execute("SELECT * FROM category_scores").fetchall()
    cat_cols = [d[0] for d in con.description]
    category_scores = [dict(zip(cat_cols, row)) for row in cats]
    categories = [{"key": k, "label": CATEGORY_LABELS.get(k, k.title()), "count": n}
                  for k, n in con.execute("SELECT category, COUNT(*) FROM topic_categories GROUP BY 1 ORDER BY 1").fetchall()]

    totals = con.execute("""SELECT (SELECT COUNT(*) FROM topics), (SELECT COUNT(*) FROM articles),
                                   (SELECT COUNT(*) FROM coverage WHERE status = 'missing'), (SELECT COUNT(*) FROM coverage)""").fetchone()

    summary = {
        "meta": {**meta, "demo": meta.get("demo") == "True", "topics": totals[0], "articles": totals[1],
                 "missingPairs": totals[2], "pairs": totals[3], "languages": len(languages)},
        "languages": languages,
        "categories": categories,
        "categoryScores": [{"lang": c["lang"], "category": c["category"], "coverage": _r(c["coverage"]),
                            "access": _r(c["access_score"], 1), "present": int(c["present"]), "topics": int(c["topics"])}
                           for c in category_scores],
    }

    # One compact record per topic: which languages have it, how deep, and the local title.
    topic_rows = con.execute("""
        SELECT c.qid, c.en_title, c.en_views, c.lang, c.status, c.depth, c.title, c.lang_views
        FROM coverage c ORDER BY c.en_views DESC, c.en_title""").fetchall()
    cat_map: dict[str, list[str]] = {}
    for qid, cat in con.execute("SELECT qid, category FROM topic_categories ORDER BY category").fetchall():
        cat_map.setdefault(qid, []).append(cat)
    topics: dict[str, dict] = {}
    for qid, en_title, en_views, lang, status, depth, title, lang_views in topic_rows:
        t = topics.setdefault(qid, {"q": qid, "t": en_title, "v": int(en_views), "c": cat_map.get(qid, []), "s": {}})
        if status != "missing":
            t["s"][lang] = [STATUS_CODE[status], _r(depth, 2), title, int(lang_views)]

    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
    (out_dir / "topics.json").write_text(json.dumps(list(topics.values()), ensure_ascii=False, separators=(",", ":")), "utf-8")
    return ["summary.json", "topics.json"]
