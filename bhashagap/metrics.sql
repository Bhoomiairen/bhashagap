-- BhashaGap metrics. Everything the dashboard shows is defined here, in plain SQL.
--
-- depth     how much of the English article's content a language article has:
--           characters of READABLE TEXT in the language article / readable text of the English
--           article, capped at 1. Readable text = what readers see, without references,
--           templates or formatting code (MediaWiki TextExtracts).
--           Fallback when text is unavailable: byte size / bytes_per_char (from languages.csv).
--           The fallback underestimates Indian-language articles, because their wiki code is
--           mostly 1-byte ASCII - that is why readable text is preferred.
-- status    missing | stub (depth < 0.15) | partial (0.15-0.5) | good (>= 0.5)
-- demand    12-month views of the English article: how much people want this topic.
-- access    Knowledge Access Score = demand-weighted average depth over ALL topics,
--           with missing articles counting as 0. "If a reader of this language looked up
--           the topics people actually read, what share of the English content would they find?"

CREATE OR REPLACE VIEW coverage AS
WITH en AS (
    SELECT t.qid, t.en_title, t.en_length, t.en_chars, COALESCE(p.views, 0) AS en_views
    FROM topics t
    LEFT JOIN pageviews p ON p.qid = t.qid AND p.lang = 'en'
),
joined AS (
    SELECT
        en.qid, en.en_title, en.en_length, en.en_chars, en.en_views,
        l.code AS lang,
        a.title,
        a.length_bytes,
        a.text_chars,
        a.last_edit,
        CASE WHEN a.qid IS NULL THEN NULL
             WHEN a.text_chars IS NOT NULL AND en.en_chars > 0 THEN LEAST(1.0, a.text_chars / en.en_chars)
             ELSE LEAST(1.0, (a.length_bytes / l.bytes_per_char) / NULLIF(en.en_length, 0)) END AS depth,
        CASE WHEN a.qid IS NULL THEN NULL
             ELSE a.last_edit >= (SELECT CAST(value AS TIMESTAMP) FROM meta WHERE key = 'run_at') - INTERVAL 365 DAY END AS fresh,
        COALESCE(lv.views, 0) AS lang_views
    FROM en
    CROSS JOIN languages l
    LEFT JOIN articles a ON a.qid = en.qid AND a.lang = l.code
    LEFT JOIN pageviews lv ON lv.qid = en.qid AND lv.lang = l.code
)
SELECT *,
    CASE WHEN title IS NULL THEN 'missing'
         WHEN depth < 0.15 THEN 'stub'
         WHEN depth < 0.5 THEN 'partial'
         ELSE 'good' END AS status,
    GREATEST(en_views, 1) AS weight
FROM joined;


CREATE OR REPLACE VIEW language_scores AS
SELECT
    l.code, l.name, l.native_name, l.script, l.speakers_millions,
    COUNT(*)                                                         AS topics,
    COUNT(c.title)                                                   AS present,
    COUNT(*) FILTER (WHERE c.status = 'missing')                     AS missing,
    COUNT(*) FILTER (WHERE c.status = 'stub')                        AS stubs,
    COUNT(*) FILTER (WHERE c.status IN ('partial', 'good'))          AS substantial,
    COUNT(c.title) / COUNT(*)                                        AS coverage,
    SUM(CASE WHEN c.title IS NOT NULL THEN c.weight ELSE 0 END) / SUM(c.weight) AS demand_coverage,
    AVG(c.depth)                                                     AS depth_of_present,
    AVG(CASE WHEN c.fresh THEN 1.0 WHEN NOT c.fresh THEN 0.0 END)    AS fresh_share,
    SUM(c.lang_views)                                                AS lang_views,
    100 * SUM(COALESCE(c.depth, 0) * c.weight) / SUM(c.weight)       AS access_score,
    CASE WHEN COUNT(c.title) > 0 THEN l.speakers_millions * 1e6 / COUNT(c.title) END AS speakers_per_article
FROM languages l
JOIN coverage c ON c.lang = l.code
GROUP BY l.code, l.name, l.native_name, l.script, l.speakers_millions;


CREATE OR REPLACE VIEW category_scores AS
SELECT
    c.lang, tc.category,
    COUNT(*)                                                    AS topics,
    COUNT(c.title)                                              AS present,
    COUNT(c.title) / COUNT(*)                                   AS coverage,
    100 * SUM(COALESCE(c.depth, 0) * c.weight) / SUM(c.weight)  AS access_score
FROM coverage c
JOIN topic_categories tc ON tc.qid = c.qid
GROUP BY c.lang, tc.category;


-- What to write first: missing articles and stubs, most-read topics first.
CREATE OR REPLACE VIEW priorities AS
SELECT
    c.lang,
    ROW_NUMBER() OVER (PARTITION BY c.lang ORDER BY c.en_views DESC, c.en_title) AS rank,
    c.qid, c.en_title, c.status, c.title AS existing_title, c.en_views
FROM coverage c
WHERE c.status IN ('missing', 'stub')
QUALIFY rank <= 100;
