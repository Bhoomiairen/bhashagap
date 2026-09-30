"""
Thin wrappers around the four Wikimedia APIs BhashaGap uses.

1. Wikidata Query Service (SPARQL)   - find topics, e.g. the 300 most documented diseases
2. MediaWiki Action API               - article size, last edit, Wikidata ID, redirects
3. Wikidata wbgetentities             - which language Wikipedias have an article on a topic
4. Wikimedia REST pageviews           - how many people read an article

Every function takes an HttpClient, so tests can swap in a fake one.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import quote

SPARQL_URL = "https://query.wikidata.org/sparql"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
PAGEVIEWS_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{project}/all-access/user/{title}/monthly/{start}/{end}"

BATCH = 50  # MediaWiki and Wikidata accept up to 50 titles / IDs per request


def chunks(items, size=BATCH):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def wiki_api(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


# ---------------------------------------------------------------- SPARQL

def sparql(client, query: str) -> list[dict]:
    """Run a SPARQL query and return rows as {variable: value} dicts."""
    body = client.get_json(SPARQL_URL, params={"query": query, "format": "json"})
    rows = []
    for binding in body["results"]["bindings"]:
        rows.append({k: v["value"] for k, v in binding.items()})
    return rows


def qid_from_uri(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


# ---------------------------------------------------------------- MediaWiki page info

def page_info(client, lang: str, titles: list[str]) -> dict[str, dict | None]:
    """
    Look up pages on one Wikipedia. Returns {requested title: info or None if missing}.
    info = {title, length, last_edit, qid}. Follows redirects and title normalisation,
    so "dengue" -> "Dengue fever" works.
    """
    result: dict[str, dict | None] = {}
    for batch in chunks(list(dict.fromkeys(titles))):
        params = {
            "action": "query", "format": "json", "formatversion": "2", "redirects": "1",
            "prop": "info|pageprops|revisions", "ppprop": "wikibase_item", "rvprop": "timestamp",
            "titles": "|".join(batch),
        }
        pages, mapping = {}, {}
        cont: dict = {}
        while True:
            # POST: Indian-script titles are long once URL-encoded
            body = client.get_json(wiki_api(lang), method="POST", data={**params, **cont})
            query = body.get("query", {})
            for n in query.get("normalized", []):
                mapping[n["from"]] = n["to"]
            for r in query.get("redirects", []):
                mapping[r["from"]] = r["to"]
            for p in query.get("pages", []):
                existing = pages.setdefault(p["title"], {})
                existing.update({k: v for k, v in p.items() if k != "revisions"} )
                if p.get("revisions"):
                    existing["revisions"] = p["revisions"]
            if "continue" not in body:
                break
            cont = body["continue"]

        for title in batch:
            final, seen = title, set()
            while final in mapping and final not in seen:  # normalised -> redirect chains
                seen.add(final)
                final = mapping[final]
            page = pages.get(final)
            if not page or page.get("missing") or page.get("invalid") or page.get("ns", 0) != 0:
                result[title] = None
                continue
            revs = page.get("revisions") or []
            result[title] = {
                "title": page["title"],
                "length": int(page.get("length", 0)),
                "last_edit": revs[0]["timestamp"] if revs else page.get("touched"),
                "qid": (page.get("pageprops") or {}).get("wikibase_item"),
            }
    return result


# ---------------------------------------------------------------- Readable text length

def text_length(client, lang: str, title: str) -> int | None:
    """
    Characters of readable text in an article: the plain text Wikipedia shows readers,
    without references, templates or formatting code. None if the page is missing.
    (TextExtracts returns full-page text for one page per request.)
    """
    body = client.get_json(wiki_api(lang), params={
        "action": "query", "format": "json", "formatversion": "2", "redirects": "1",
        "prop": "extracts", "explaintext": "1", "exsectionformat": "plain", "titles": title,
    })
    pages = body.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing") or pages[0].get("extract") is None:
        return None
    return len(" ".join(pages[0]["extract"].split()))  # collapse whitespace


# ---------------------------------------------------------------- Wikidata sitelinks

def sitelinks(client, qids: list[str], wikis: list[str]) -> dict[str, dict[str, str]]:
    """
    For each Wikidata item, which of the given wikis have an article, and its title.
    Returns {qid: {"hiwiki": "डेंगू", ...}}. Merged/redirected items are mapped back
    to the ID we asked for.
    """
    out: dict[str, dict[str, str]] = {}
    for batch in chunks(list(dict.fromkeys(qids))):
        body = client.get_json(WIKIDATA_API, params={
            "action": "wbgetentities", "format": "json", "props": "sitelinks",
            "ids": "|".join(batch), "sitefilter": "|".join(wikis),
        })
        entities = body.get("entities", {})
        for key, ent in entities.items():
            if "missing" in ent:
                continue
            asked = ent.get("redirects", {}).get("from", key)
            links = ent.get("sitelinks", {}) or {}
            out[asked] = {site: link["title"] for site, link in links.items() if site in wikis}
        for q in batch:
            out.setdefault(q, {})
    return out


# ---------------------------------------------------------------- Pageviews

def last_full_months(n: int = 12, today: date | None = None) -> tuple[str, str]:
    """Start/end timestamps covering the last n complete months, in the API's format."""
    today = today or date.today()
    y, m = today.year, today.month - 1  # previous month is the last complete one
    if m == 0:
        y, m = y - 1, 12
    end = f"{y:04d}{m:02d}0100"
    sm, sy = m - (n - 1), y
    while sm <= 0:
        sm += 12
        sy -= 1
    start = f"{sy:04d}{sm:02d}0100"
    return start, end


def monthly_views(client, project: str, title: str, start: str, end: str) -> int:
    """Total human (non-bot) views of an article over the period. 0 if no data."""
    url = PAGEVIEWS_URL.format(project=project, title=quote(title.replace(" ", "_"), safe=""), start=start, end=end)
    body = client.get_json(url, allow_404=True)
    if not body:
        return 0
    return sum(int(item.get("views", 0)) for item in body.get("items", []))
