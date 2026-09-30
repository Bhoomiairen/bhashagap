"""
A fake Wikimedia that answers exactly like the real APIs do (same JSON shapes),
so the whole pipeline can be tested without the internet.

World:
  English: "Dengue" redirects to "Dengue fever" (Q30953); "tuberculosis" is normalised to
           "Tuberculosis" (Q12204); "Rice" (Q5090); "HIV/AIDS" (Q12199); "Nonexistent topic" is missing.
  SPARQL "diseases" returns Dengue fever and Malaria (Q12156).
  Hindi has Dengue, TB, Rice, HIV/AIDS, Malaria. Marathi has only TB (a stub) and Rice.
  Q12156 (Malaria) is returned by Wikidata under a redirect from the asked ID.
"""

from urllib.parse import unquote

EN = {
    "Dengue fever": {"qid": "Q30953", "length": 60000},
    "Tuberculosis": {"qid": "Q12204", "length": 90000},
    "Rice": {"qid": "Q5090", "length": 30000},
    "HIV/AIDS": {"qid": "Q12199", "length": 80000},
    "Malaria": {"qid": "Q12156", "length": 70000},
}
REDIRECTS = {"en": {"Dengue": "Dengue fever"}}
NORMALISE = {"tuberculosis": "Tuberculosis"}

SITELINKS = {
    "Q30953": {"hiwiki": "डेंगू बुख़ार"},
    "Q12204": {"hiwiki": "क्षय रोग", "mrwiki": "क्षयरोग"},
    "Q5090": {"hiwiki": "चावल", "mrwiki": "तांदूळ"},
    "Q12199": {"hiwiki": "एड्स"},
    "Q12156": {"hiwiki": "मलेरिया"},
}
# bytes of each language article (Devanagari ~3 bytes per character)
LANG_PAGES = {
    "hi": {"डेंगू बुख़ार": 90000, "क्षय रोग": 27000, "चावल": 90000, "एड्स": 12000, "मलेरिया": 210000},
    "mr": {"क्षयरोग": 6000, "तांदूळ": 45000},
}
EDITS = {"मलेरिया": "2019-03-01T10:00:00Z"}
# readable-text characters (TextExtracts). Same depths as the byte sizes above, so both paths agree.
# Marathi "तांदूळ" has no extract -> the pipeline must fall back to byte size.
TEXT = {"en": {"Dengue fever": 30000, "Tuberculosis": 45000, "Rice": 15000, "HIV/AIDS": 40000, "Malaria": 35000},
        "hi": {"डेंगू बुख़ार": 15000, "क्षय रोग": 4500, "चावल": 15000, "एड्स": 2000, "मलेरिया": 35000},
        "mr": {"क्षयरोग": 900}}  # everything else edited recently
VIEWS = {("en.wikipedia", "Dengue_fever"): [1000, 2000], ("en.wikipedia", "Tuberculosis"): [3000, 3000],
         ("en.wikipedia", "Rice"): [500, 500], ("en.wikipedia", "HIV/AIDS"): [4000, 0],
         ("hi.wikipedia", "डेंगू_बुख़ार"): [100, 50]}


class FakeClient:
    def __init__(self):
        self.calls = []
        self.stats = {"network": 0, "cache": 0, "errors": 0}

    def get_json(self, url, params=None, method="GET", data=None, allow_404=False):
        self.calls.append((method, url, params or data))
        self.stats["network"] += 1
        if "query.wikidata.org" in url:
            return self._sparql()
        if "www.wikidata.org" in url:
            return self._entities(params)
        if "wikimedia.org/api/rest_v1" in url:
            return self._views(url)
        lang = url.split("//")[1].split(".")[0]
        if params and params.get("prop") == "extracts":
            return self._extract(lang, params["titles"])
        return self._pages(lang, data)

    def _extract(self, lang, title):
        n = TEXT.get(lang, {}).get(title)
        if n is None:
            return {"batchcomplete": True, "query": {"pages": [{"ns": 0, "title": title, "missing": True}]}}
        text = ("क " * (n // 2)) if lang != "en" else ("a " * (n // 2))  # n characters incl. spaces
        return {"batchcomplete": True, "query": {"pages": [{"pageid": 1, "ns": 0, "title": title, "extract": "\n\n" + text.strip() + "x"}]}}

    def _sparql(self):
        def row(q, t, n):
            return {"item": {"type": "uri", "value": f"http://www.wikidata.org/entity/{q}"},
                    "enTitle": {"xml:lang": "en", "type": "literal", "value": t},
                    "sitelinks": {"datatype": "http://www.w3.org/2001/XMLSchema#integer", "type": "literal", "value": str(n)}}
        return {"head": {"vars": ["item", "enTitle", "sitelinks"]},
                "results": {"bindings": [row("Q30953", "Dengue fever", 120), row("Q12156", "Malaria", 200)]}}

    def _entities(self, params):
        wikis = params["sitefilter"].split("|")
        entities = {}
        for qid in params["ids"].split("|"):
            if qid not in SITELINKS:
                entities[qid] = {"id": qid, "missing": ""}
                continue
            links = {w: {"site": w, "title": t, "badges": []} for w, t in SITELINKS[qid].items() if w in wikis}
            ent = {"type": "item", "id": qid, "sitelinks": links}
            if qid == "Q12156":  # simulate a merged item: Wikidata answers under a different ID
                ent = {**ent, "id": "Q999", "redirects": {"from": "Q12156", "to": "Q999"}}
                entities["Q999"] = ent
            else:
                entities[qid] = ent
        return {"entities": entities, "success": 1}

    def _pages(self, lang, data):
        titles = data["titles"].split("|")
        query = {"normalized": [], "redirects": [], "pages": []}
        for t in titles:
            final = t
            if t in NORMALISE:
                query["normalized"].append({"fromencoded": False, "from": t, "to": NORMALISE[t]})
                final = NORMALISE[t]
            if final in REDIRECTS.get(lang, {}):
                query["redirects"].append({"from": final, "to": REDIRECTS[lang][final]})
                final = REDIRECTS[lang][final]
            if lang == "en" and final in EN:
                p = EN[final]
                query["pages"].append({"pageid": 1, "ns": 0, "title": final, "contentmodel": "wikitext", "length": p["length"],
                                       "touched": "2026-09-01T00:00:00Z", "pageprops": {"wikibase_item": p["qid"]},
                                       "revisions": [{"timestamp": "2026-09-10T08:00:00Z"}]})
            elif lang != "en" and final in LANG_PAGES.get(lang, {}):
                query["pages"].append({"pageid": 2, "ns": 0, "title": final, "length": LANG_PAGES[lang][final],
                                       "touched": "2026-09-01T00:00:00Z",
                                       "revisions": [{"timestamp": EDITS.get(final, "2026-06-01T00:00:00Z")}]})
            else:
                query["pages"].append({"ns": 0, "title": final, "missing": True})
        return {"batchcomplete": True, "query": query}

    def _views(self, url):
        parts = url.split("/per-article/")[1].split("/")
        project, title = parts[0], unquote(parts[3])
        months = VIEWS.get((project, title))
        if months is None:
            return None  # the real API answers 404 when there is no data
        return {"items": [{"project": project, "article": title, "granularity": "monthly", "timestamp": f"20250{i+1}0100",
                           "access": "all-access", "agent": "user", "views": v} for i, v in enumerate(months)]}
