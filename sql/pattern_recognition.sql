/* TASK 9 — Pattern Recognition with MATCH_RECOGNIZE.

   Goal: formally detect COVID-19 "waves" (a sustained rise in daily new
   cases followed by a sustained fall) per country, using Snowflake's
   MATCH_RECOGNIZE row pattern matching, instead of relying on eyeballing
   a rolling-average chart the way Section 3.5 originally did.
*/

-- --------------------------------------------------------------------
-- Step 1: a smoothed base table.
--
-- Raw daily NEW_CASES is too noisy for pattern matching directly (day-of-
-- week reporting effects, established in Task 2/3.5, create false ups and
-- downs). A 7-day rolling average, already used elsewhere in this project
-- (Task 4's /cases/rolling-average), removes that noise first.
--
-- Reads from COVID19_ANALYTICS.PUBLIC.NATIONAL_DAILY_CASES (Task 7), the
-- same pre-aggregated, clustered table the API uses, rather than
-- re-aggregating JHU_COVID_19 again here.
-- --------------------------------------------------------------------

CREATE OR REPLACE TABLE COVID19_ANALYTICS.PUBLIC.SMOOTHED_NEW_CASES AS
SELECT
    COUNTRY_REGION,
    DATE,
    NEW_CASES,
    SMOOTHED_NEW_CASES,
    -- IS_UP / IS_DOWN compare against the value 3 days earlier, not the
    -- immediately preceding day. A single noisy day (one small dip inside
    -- an otherwise clear uptrend) would otherwise break a long UP run for
    -- MATCH_RECOGNIZE's strict day-over-day DEFINE, and a real multi-week
    -- wave would get missed entirely. Confirmed live: with a 1-day
    -- comparison, the whole December 2021-January 2022 Omicron surge in
    -- the US was not detected as a wave at all, because a single down day
    -- on 2021-12-13 split it into two unmatchable fragments. Comparing
    -- against 3 days back tolerates that kind of single-day noise.
    SMOOTHED_NEW_CASES > LAG(SMOOTHED_NEW_CASES, 3) OVER (PARTITION BY COUNTRY_REGION ORDER BY DATE) AS IS_UP,
    SMOOTHED_NEW_CASES < LAG(SMOOTHED_NEW_CASES, 3) OVER (PARTITION BY COUNTRY_REGION ORDER BY DATE) AS IS_DOWN
FROM (
    SELECT
        COUNTRY_REGION,
        DATE,
        NEW_CASES,
        AVG(NEW_CASES) OVER (
            PARTITION BY COUNTRY_REGION ORDER BY DATE
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ) AS SMOOTHED_NEW_CASES
    FROM COVID19_ANALYTICS.PUBLIC.NATIONAL_DAILY_CASES
    WHERE CASE_TYPE = 'Confirmed'
);

/* --------------------------------------------------------------------
   A note on why IS_UP/IS_DOWN are precomputed here, outside
   MATCH_RECOGNIZE, instead of calling PREV() inside its DEFINE clause
   (the pattern shown in Snowflake's own documentation).

   Both of these were tried and failed on this account:

     DEFINE UP AS SMOOTHED_NEW_CASES > PREV(SMOOTHED_NEW_CASES)
       -> "Unsupported feature 'this window function and semantic
           combination does currently not support pattern variable
           predicates'"

   This was reproduced even against a trivial 5-row literal VALUES table
   with no window functions involved at all, using the exact V-shape
   example from Snowflake's own MATCH_RECOGNIZE documentation, ruling out
   a mistake specific to this project's query. Since the underlying issue
   is with PREV() itself in DEFINE, the workaround is to compute the
   "is this row higher/lower than N rows ago" comparison as a plain
   boolean column beforehand (via LAG(), a normal window function with no
   restriction), and have DEFINE reference that already-computed column
   directly, with no navigation function inside MATCH_RECOGNIZE at all.
   -------------------------------------------------------------------- */

-- --------------------------------------------------------------------
-- Step 2: detect waves with MATCH_RECOGNIZE.
--
-- PATTERN (STRT UP{3,} DOWN{3,}) reads as: an anchor row, then at least 3
-- rows where the smoothed series is rising, then at least 3 rows where it
-- is falling. AFTER MATCH SKIP PAST LAST ROW means the next search starts
-- right after the current match ends, so waves don't overlap.
-- --------------------------------------------------------------------

SELECT
    COUNTRY_REGION,
    WAVE_NUMBER,
    WAVE_START,
    PEAK_DATE,
    WAVE_END,
    ROUND(PEAK_VALUE) AS PEAK_SMOOTHED_NEW_CASES
FROM (
    SELECT * FROM COVID19_ANALYTICS.PUBLIC.SMOOTHED_NEW_CASES
    WHERE COUNTRY_REGION = 'United States'
)
MATCH_RECOGNIZE (
    PARTITION BY COUNTRY_REGION
    ORDER BY DATE
    MEASURES
        FIRST(UP.DATE)          AS WAVE_START,
        LAST(UP.DATE)           AS PEAK_DATE,
        LAST(DOWN.DATE)         AS WAVE_END,
        MAX(SMOOTHED_NEW_CASES) AS PEAK_VALUE,
        MATCH_NUMBER()          AS WAVE_NUMBER
    ONE ROW PER MATCH
    AFTER MATCH SKIP PAST LAST ROW
    PATTERN (STRT UP{3,} DOWN{3,})
    DEFINE
        UP   AS IS_UP,
        DOWN AS IS_DOWN
)
ORDER BY WAVE_NUMBER;

/* --------------------------------------------------------------------
   Result for the United States (30 waves detected across 2020-01-22 to
   2023-03-09). The largest by peak smoothed value:

     WAVE_START   PEAK_DATE    WAVE_END     PEAK_SMOOTHED_NEW_CASES
     2021-12-15   2022-01-16   2022-01-19   806,966

   This is the same Omicron wave already identified three separate ways
   earlier in this project: visually in the 7-day rolling average chart
   (Section 3.3/6.3), as a MongoDB annotation dated 2022-01-10 ("Omicron
   wave peak in the US"), and now independently, algorithmically, via
   MATCH_RECOGNIZE, with a peak date landing in the same narrow window.
   Three different methods agreeing on the same event is a much stronger
   basis for a finding than any one of them alone.

   The same query run for Germany (COUNTRY_REGION = 'Germany') also
   surfaces its two largest waves in the January-April 2022 window,
   consistent with Germany's own Omicron/BA.2 wave in that period,
   confirming this is not a pattern specific to how the US reports data.
   -------------------------------------------------------------------- */

-- Same query, run for Germany, to confirm the pattern generalizes:
SELECT
    COUNTRY_REGION,
    WAVE_NUMBER,
    WAVE_START,
    PEAK_DATE,
    WAVE_END,
    ROUND(PEAK_VALUE) AS PEAK_SMOOTHED_NEW_CASES
FROM (
    SELECT * FROM COVID19_ANALYTICS.PUBLIC.SMOOTHED_NEW_CASES
    WHERE COUNTRY_REGION = 'Germany'
)
MATCH_RECOGNIZE (
    PARTITION BY COUNTRY_REGION
    ORDER BY DATE
    MEASURES
        FIRST(UP.DATE)          AS WAVE_START,
        LAST(UP.DATE)           AS PEAK_DATE,
        LAST(DOWN.DATE)         AS WAVE_END,
        MAX(SMOOTHED_NEW_CASES) AS PEAK_VALUE,
        MATCH_NUMBER()          AS WAVE_NUMBER
    ONE ROW PER MATCH
    AFTER MATCH SKIP PAST LAST ROW
    PATTERN (STRT UP{3,} DOWN{3,})
    DEFINE
        UP   AS IS_UP,
        DOWN AS IS_DOWN
)
ORDER BY PEAK_SMOOTHED_NEW_CASES DESC
LIMIT 10;