"""
The collection steps. Each returns plain Python rows, which store.py loads into DuckDB.

  1. topics      curated title lists + SPARQL queries  -> Wikidata IDs + English article info
  2. coverage    Wikidata sitelinks                     -> which Indian-language Wikipedias have each topic
  3. articles    MediaWiki API on each language wiki   -> size and last edit of every existing article
  4. pageviews   Wikimedia REST API                     -> 12-month readership (English + each language)
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from . import wikimedia as wm
from .config import Language, load_curated_topics, sparql_queries


def log(msg: str):
    print(msg, flush=True)


def collect_topics(client, limit: int | None = None):
    """Returns (topics, topic_categories, unresolved).
    topics: {qid: {qid, en_title, en_length, en_last_edit}}"""
    by_category: dict[str, list[str]] = {}

    curated = load_curated_topics()
    for category, titles in curated.items():
        by_category[category] = titles[:limit] if limit else titles
    for category, query in sparql_queries().items():
        rows = wm.sparql(client, query)
        titles = [r["enTitle"] for r in rows]
        by_category[category] = titles[:limit] if limit else titles
        log(f"  SPARQL '{category}': {len(rows)} topics")

    all_titles = [t for titles in by_category.values() for t in titles]
    info = wm.page_info(client, "en", all_titles)

    topics, links, unresolved = {}, set(), []
    for category, titles in by_category.items():
        for title in titles:
            page = info.get(title)
            if not page or not page["qid"]:
                unresolved.append((category, title))
                continue
            qid = page["qid"]
            topics.setdefault(qid, {"qid": qid, "en_title": page["title"], "en_length": page["length"], "en_last_edit": page["last_edit"]})
            links.add((qid, category))
    log(f"  {len(topics)} unique topics resolved, {len(unresolved)} titles not found")
    return topics, sorted(links), unresolved


def collect_coverage(client, qids: list[str], languages: list[Language]):
    """Rows of (qid, lang, title) for every language article that exists."""
    wikis = [l.wiki for l in languages]
    links = wm.sitelinks(client, qids, wikis)
    code_by_wiki = {l.wiki: l.code for l in languages}
    rows = [(qid, code_by_wiki[w], title) for qid, sites in links.items() for w, title in sites.items()]
    log(f"  {len(rows)} language articles found across {len(languages)} languages")
    return rows


def collect_articles(client, coverage_rows, languages: list[Language]):
    """Rows of (qid, lang, title, length_bytes, last_edit)."""
    by_lang: dict[str, list[tuple[str, str]]] = {}
    for qid, lang, title in coverage_rows:
        by_lang.setdefault(lang, []).append((qid, title))
    out = []
    for lang in [l.code for l in languages]:
        items = by_lang.get(lang, [])
        if not items:
            continue
        info = wm.page_info(client, lang, [t for _, t in items])
        for qid, title in items:
            page = info.get(title)
            if page:  # sitelink can point to a page that was since deleted
                out.append((qid, lang, page["title"], page["length"], page["last_edit"]))
        log(f"  {lang}: {len(items)} articles checked")
    return out


def collect_text(client, topics: dict, article_rows, workers: int = 6):
    """Readable-text length of every English topic article and every language article.
    Returns ({qid: en_chars}, {(qid, lang): chars})."""
    jobs = [(qid, "en", t["en_title"]) for qid, t in topics.items()] + [(qid, lang, title) for qid, lang, title, *_ in article_rows]
    log(f"  measuring readable text of {len(jobs)} articles (cached after the first run)")
    en_chars, lang_chars = {}, {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(wm.text_length, client, lang, title): (qid, lang) for qid, lang, title in jobs}
        for i, fut in enumerate(as_completed(futures), 1):
            qid, lang = futures[fut]
            n = fut.result()
            if lang == "en":
                en_chars[qid] = n
            else:
                lang_chars[(qid, lang)] = n
            if i % 500 == 0:
                log(f"    {i}/{len(jobs)}")
    return en_chars, lang_chars


def collect_pageviews(client, topics: dict, article_rows, languages: list[Language], months: int = 12, workers: int = 6,
                      include_languages: bool = True):
    """Rows of (qid, lang, views). lang='en' is the English article (used as a measure of demand)."""
    start, end = wm.last_full_months(months)
    jobs = [(qid, "en", "en.wikipedia", t["en_title"]) for qid, t in topics.items()]
    if include_languages:
        projects = {l.code: l.project for l in languages}
        jobs += [(qid, lang, projects[lang], title) for qid, lang, title, *_ in article_rows]
    log(f"  fetching views {start[:6]}–{end[:6]} for {len(jobs)} articles (cached after the first run)")

    out = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(wm.monthly_views, client, project, title, start, end): (qid, lang) for qid, lang, project, title in jobs}
        for i, fut in enumerate(as_completed(futures), 1):
            qid, lang = futures[fut]
            out.append((qid, lang, fut.result()))
            if i % 500 == 0:
                log(f"    {i}/{len(jobs)}")
    return out, (start, end)
