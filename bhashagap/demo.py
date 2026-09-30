"""
Demo data so the website works before you've run the real pipeline.

EVERYTHING HERE IS RANDOMLY GENERATED. The site shows a "demo data" banner while
it is in use. Never quote these numbers - run `python -m bhashagap run` for real ones.
"""

import random

from .config import load_curated_topics


def make_demo(languages, seed: int = 7):
    rng = random.Random(seed)
    topics, cats, articles, views = {}, [], [], []
    # rough "size" of each Wikipedia so the demo looks plausible (bigger = more articles)
    strength = {l.code: max(0.08, min(0.92, 0.25 + 0.12 * (l.speakers_millions ** 0.33) / 2 + rng.uniform(-0.15, 0.15))) for l in languages}

    n = 0
    for category, titles in load_curated_topics().items():
        for title in titles:
            n += 1
            qid = f"DEMO{n}"
            en_len = int(rng.lognormvariate(10.3, 0.6))
            topics[qid] = {"qid": qid, "en_title": title, "en_length": en_len, "en_last_edit": "2026-08-01T00:00:00Z", "en_chars": en_len // 2}
            cats.append((qid, category))
            popularity = rng.lognormvariate(12.5, 1.1)
            views.append((qid, "en", int(popularity)))
            for l in languages:
                p = strength[l.code] * (1.1 if category in ("health", "science") else 0.9)
                if rng.random() < p:
                    ratio = min(1.2, rng.betavariate(1.3, 3.5) * (0.6 + strength[l.code]))
                    length = int(en_len * ratio * l.bytes_per_char)
                    month = rng.randint(1, 12)
                    year = 2026 if rng.random() < 0.55 else rng.choice([2019, 2021, 2023, 2024])
                    articles.append((qid, l.code, title, length, f"{year}-{month:02d}-15T00:00:00Z", int(en_len // 2 * ratio)))
                    views.append((qid, l.code, int(popularity * strength[l.code] * rng.uniform(0.002, 0.05))))
    return topics, cats, articles, views
