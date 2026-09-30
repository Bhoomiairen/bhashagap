"""Paths and the two inputs the pipeline starts from: languages and topic lists."""

import csv
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "raw" / "cache"
PROCESSED_DIR = DATA_DIR / "processed"
DB_PATH = DATA_DIR / "bhashagap.duckdb"
SITE_DATA_DIR = ROOT / "site" / "data"

# Human-readable names for the topic files in config/topics/
CATEGORY_LABELS = {
    "health": "Health",
    "agriculture": "Farming & food",
    "rights": "Schemes & rights",
    "science": "Science & environment",
    "money": "Money & work",
    "diseases": "Diseases (top 300)",
}


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    native_name: str
    script: str
    speakers_millions: float
    bytes_per_char: int

    @property
    def wiki(self) -> str:  # Wikidata sitelink key, e.g. "hiwiki"
        return f"{self.code}wiki"

    @property
    def project(self) -> str:  # Wikimedia project name, e.g. "hi.wikipedia"
        return f"{self.code}.wikipedia"


def load_languages(only: list[str] | None = None) -> list[Language]:
    with open(CONFIG_DIR / "languages.csv", encoding="utf-8") as f:
        langs = [
            Language(r["code"], r["name"], r["native_name"], r["script"], float(r["speakers_millions"]), int(r["bytes_per_char"]))
            for r in csv.DictReader(f)
        ]
    if only:
        wanted = set(only)
        unknown = wanted - {l.code for l in langs}
        if unknown:
            raise SystemExit(f"Unknown language code(s): {', '.join(sorted(unknown))}. See config/languages.csv")
        langs = [l for l in langs if l.code in wanted]
    return langs


def load_curated_topics() -> dict[str, list[str]]:
    """{category: [English Wikipedia titles]} from config/topics/*.txt (comments and blanks ignored)."""
    topics = {}
    for path in sorted((CONFIG_DIR / "topics").glob("*.txt")):
        titles = []
        for line in path.read_text("utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                titles.append(line)
        topics[path.stem] = titles
    return topics


def sparql_queries() -> dict[str, str]:
    """{category: SPARQL query} from config/sparql/*.rq"""
    return {p.stem: p.read_text("utf-8") for p in sorted((CONFIG_DIR / "sparql").glob("*.rq"))}
