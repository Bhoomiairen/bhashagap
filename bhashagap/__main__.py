"""
BhashaGap command line.

    python -m bhashagap run                 # full real run (first time ~20-30 min, then cached)
    python -m bhashagap run --limit 10      # quick test: 10 topics per category
    python -m bhashagap run --langs hi,mr   # only some languages
    python -m bhashagap demo                # random demo data for the website
    python -m bhashagap export              # rebuild CSV/JSON from the existing database
"""

import argparse
import csv
import time

import duckdb

from . import collect, export, store
from .config import CACHE_DIR, DB_PATH, PROCESSED_DIR, SITE_DATA_DIR, load_languages
from .demo import make_demo
from .http import HttpClient


def cmd_run(args):
    languages = load_languages(args.langs.split(",") if args.langs else None)
    client = HttpClient(CACHE_DIR, requests_per_second=args.rps, offline=args.offline)
    t0 = time.time()

    print("1/6  Topics: curated lists + Wikidata SPARQL")
    topics, topic_cats, unresolved = collect.collect_topics(client, limit=args.limit)
    print("2/6  Coverage: Wikidata sitelinks")
    coverage = collect.collect_coverage(client, list(topics), languages)
    print("3/6  Articles: size and last edit on each language Wikipedia")
    articles = collect.collect_articles(client, coverage, languages)
    if args.no_text:
        print("4/6  Readable text: skipped (depth will use byte size, which underestimates Indian languages)")
    else:
        print("4/6  Readable text: characters of plain text in every article")
        en_chars, lang_chars = collect.collect_text(client, topics, articles)
        for qid, n in en_chars.items():
            topics[qid]["en_chars"] = n
        articles = [(*row, lang_chars.get((row[0], row[1]))) for row in articles]
    if args.no_pageviews:
        print("5/6  Pageviews: skipped")
        views, period = [], ("", "")
    else:
        print("5/6  Pageviews: 12 months of readership")
        views, period = collect.collect_pageviews(client, topics, articles, languages, include_languages=not args.no_lang_views)

    print("6/6  Building database and exports")
    con = store.build(DB_PATH, languages, topics, topic_cats, articles, views, meta={
        "demo": False, "period_start": period[0][:6], "period_end": period[1][:6],
        "api_requests": client.stats["network"] + client.stats["cache"],
    })
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_DIR / "unresolved_titles.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["category", "title"])
        w.writerows(unresolved)
    _export(con)
    print(f"\nDone in {time.time() - t0:.0f}s. Requests: {client.stats['network']} from the network, "
          f"{client.stats['cache']} from cache.")
    if unresolved:
        print(f"{len(unresolved)} topic titles weren't found on English Wikipedia - see data/processed/unresolved_titles.csv")
    _print_top(con)


def cmd_demo(args):
    languages = load_languages()
    topics, cats, articles, views = make_demo(languages)
    con = store.build(DB_PATH, languages, topics, cats, articles, views,
                      meta={"demo": True, "period_start": "202509", "period_end": "202608", "api_requests": 0})
    _export(con)
    print("Demo data written. The website will show a 'demo data' banner until you do a real run.")


def cmd_export(args):
    if not DB_PATH.exists():
        raise SystemExit("No database yet. Run `python -m bhashagap run` (or `demo`) first.")
    con = duckdb.connect(str(DB_PATH))
    store.create_views(con)
    _export(con)


def _export(con):
    csvs = export.export_csv(con, PROCESSED_DIR)
    site = export.export_site(con, SITE_DATA_DIR)
    print(f"  dataset  -> data/processed/ ({', '.join(csvs)})")
    print(f"  website  -> site/data/ ({', '.join(site)})")


def _print_top(con):
    rows = con.execute("SELECT name, ROUND(access_score, 1), present, topics FROM language_scores ORDER BY access_score DESC").fetchall()
    print("\nKnowledge Access Score (0-100):")
    for name, score, present, total in rows:
        print(f"  {name:<10} {score:>5}   {present}/{total} topics have an article")


def main():
    parser = argparse.ArgumentParser(prog="bhashagap", description="Measure how much essential knowledge is missing in Indian-language Wikipedias.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="collect real data from Wikimedia APIs")
    run.add_argument("--langs", help="comma-separated language codes (default: all in config/languages.csv)")
    run.add_argument("--limit", type=int, help="only the first N topics of each category (quick test)")
    run.add_argument("--rps", type=float, default=8.0, help="max requests per second (default 8)")
    run.add_argument("--no-pageviews", action="store_true", help="skip readership data (much faster)")
    run.add_argument("--no-lang-views", action="store_true", help="skip readership of language articles")
    run.add_argument("--no-text", action="store_true", help="skip readable-text measurement (faster, less accurate)")
    run.add_argument("--offline", action="store_true", help="use only cached responses")
    run.set_defaults(func=cmd_run)
    sub.add_parser("demo", help="write random demo data for the website").set_defaults(func=cmd_demo)
    sub.add_parser("export", help="re-export CSV/JSON from the existing database").set_defaults(func=cmd_export)
    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        raise SystemExit("\nStopped. Everything downloaded so far is cached - run the same command again to continue.")
    except RuntimeError as err:
        raise SystemExit(f"\nError: {err}\nCheck your internet connection and run the same command again; finished requests are cached.")


if __name__ == "__main__":
    main()
