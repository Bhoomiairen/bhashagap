"""End-to-end pipeline tests against a fake Wikimedia (tests/fake_wikimedia.py).  Run:  python -m pytest -q"""

import json
from datetime import date

import pytest

from bhashagap import collect, export, store
from bhashagap import wikimedia as wm
from bhashagap.config import load_languages

from .fake_wikimedia import FakeClient


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setattr(collect, "load_curated_topics", lambda: {"health": ["Dengue", "tuberculosis", "HIV/AIDS", "Nonexistent topic"], "agriculture": ["Rice"]})
    monkeypatch.setattr(collect, "sparql_queries", lambda: {"diseases": "SELECT ..."})
    client = FakeClient()
    langs = load_languages(["hi", "mr"])
    topics, cats, unresolved = collect.collect_topics(client)
    coverage = collect.collect_coverage(client, list(topics), langs)
    articles = collect.collect_articles(client, coverage, langs)
    en_chars, lang_chars = collect.collect_text(client, topics, articles)
    for qid, n in en_chars.items():
        topics[qid]["en_chars"] = n
    articles = [(*row, lang_chars.get((row[0], row[1]))) for row in articles]
    views, period = collect.collect_pageviews(client, topics, articles, langs)
    con = store.build(tmp_path / "t.duckdb", langs, topics, cats, articles, views, meta={"demo": False, "run_at": "2026-09-28T00:00:00"})
    return {"client": client, "topics": topics, "cats": cats, "unresolved": unresolved, "coverage": coverage,
            "articles": articles, "views": views, "con": con, "tmp": tmp_path}


def test_topics_resolve_redirects_normalisation_and_sparql(world):
    assert set(world["topics"]) == {"Q30953", "Q12204", "Q12199", "Q5090", "Q12156"}
    assert world["topics"]["Q30953"]["en_title"] == "Dengue fever"  # "Dengue" redirect followed
    assert world["unresolved"] == [("health", "Nonexistent topic")]
    # Dengue is both a curated health topic and a SPARQL disease
    assert {c for q, c in world["cats"] if q == "Q30953"} == {"health", "diseases"}


def test_coverage_handles_merged_wikidata_items(world):
    rows = {(q, l) for q, l, _ in world["coverage"]}
    assert ("Q12156", "hi") in rows  # returned by Wikidata under a redirect, mapped back
    assert ("Q30953", "mr") not in rows
    assert len(rows) == 7


def test_articles_have_size_and_edit_date(world):
    art = {(q, l): (length, edit) for q, l, _, length, edit, _chars in world["articles"]}
    assert art[("Q12204", "mr")] == (6000, "2026-06-01T00:00:00Z")
    assert art[("Q12156", "hi")][1] == "2019-03-01T10:00:00Z"


def test_readable_text_measured_with_fallback(world):
    chars = {(q, l): c for q, l, _, _, _, c in world["articles"]}
    assert chars[("Q30953", "hi")] == 15000
    assert chars[("Q5090", "mr")] is None       # no extract -> None, depth falls back to bytes
    assert world["topics"]["Q12204"]["en_chars"] == 45000
    depth = world["con"].execute("SELECT depth FROM coverage WHERE qid = 'Q5090' AND lang = 'mr'").fetchone()[0]
    assert depth == 0.5                          # 45000 bytes / 3 = 15000 chars vs 30000 English bytes


def test_pageviews_sum_months_and_missing_is_zero(world):
    views = {(q, l): v for q, l, v in world["views"]}
    assert views[("Q30953", "en")] == 3000
    assert views[("Q12156", "en")] == 0      # API 404 -> no views
    assert views[("Q30953", "hi")] == 150     # Indian-script title URL-encoded correctly
    assert views[("Q12199", "en")] == 4000    # "HIV/AIDS": slash encoded as %2F


def test_metrics(world):
    con = world["con"]
    cov = {(q, l): (s, d) for q, l, s, d in con.execute("SELECT qid, lang, status, depth FROM coverage").fetchall()}
    # Marathi TB: 6000 bytes / 3 = 2000 chars vs 90000 English -> 0.022 -> stub
    assert cov[("Q12204", "mr")][0] == "stub"
    # Hindi Malaria: 210000/3 = 70000 chars = English length -> depth 1, good
    assert cov[("Q12156", "hi")] == ("good", 1.0)
    assert cov[("Q30953", "mr")] == ("missing", None)

    hi = con.execute("SELECT present, topics, coverage, fresh_share, access_score FROM language_scores WHERE code = 'hi'").fetchone()
    assert hi[:3] == (5, 5, 1.0)
    assert hi[3] == pytest.approx(0.8)  # Malaria article last edited in 2019
    # access = weighted depth. weights: Dengue 3000, TB 6000, Rice 1000, HIV 4000, Malaria 1 (no views -> 1)
    depths = {"Q30953": 0.5, "Q12204": 0.1, "Q5090": 1.0, "Q12199": 0.05, "Q12156": 1.0}
    weights = {"Q30953": 3000, "Q12204": 6000, "Q5090": 1000, "Q12199": 4000, "Q12156": 1}
    expected = 100 * sum(depths[q] * weights[q] for q in depths) / sum(weights.values())
    assert hi[4] == pytest.approx(expected)

    mr_priorities = con.execute("SELECT rank, en_title, status FROM priorities WHERE lang = 'mr' ORDER BY rank").fetchall()
    assert mr_priorities[0] == (1, "Tuberculosis", "stub")   # most-read topic, only a stub in Marathi
    assert [t for _, t, _ in mr_priorities] == ["Tuberculosis", "HIV/AIDS", "Dengue fever", "Malaria"]


def test_exports(world):
    con, tmp = world["con"], world["tmp"]
    export.export_csv(con, tmp / "csv")
    export.export_site(con, tmp / "site")
    summary = json.loads((tmp / "site" / "summary.json").read_text("utf-8"))
    assert summary["meta"]["topics"] == 5 and summary["meta"]["demo"] is False
    assert [l["code"] for l in summary["languages"]] == ["hi", "mr"]  # sorted by access score
    topics = json.loads((tmp / "site" / "topics.json").read_text("utf-8"))
    tb = next(t for t in topics if t["q"] == "Q12204")
    assert tb["s"]["mr"][0] == 1 and "hi" in tb["s"] and sorted(tb["c"]) == ["health"]
    assert (tmp / "csv" / "priorities.csv").read_text("utf-8").startswith("lang,rank,qid")


def test_last_full_months():
    assert wm.last_full_months(12, date(2026, 9, 28)) == ("2025090100", "2026080100")
    assert wm.last_full_months(12, date(2026, 1, 5)) == ("2025010100", "2025120100")
