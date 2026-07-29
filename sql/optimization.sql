/* TASK 7 — Performance optimization.

   Context: JHU_COVID_19 is a Secure Data Share (imported database), so this
   account does not own it and cannot alter it (no clustering key, no
   materialized view, no dynamic table can be created directly on it). The
   attempt below documents that constraint before working around it.
*/

-- 1. Confirms the shared table has no clustering key and no owner in this
--    account (owner column is blank for a share).
SHOW TABLES LIKE 'JHU_COVID_19' IN SCHEMA COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC;

-- 2. Attempting to alter the shared table directly. Expected to fail because
--    this account does not own the underlying object.
ALTER TABLE COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
  CLUSTER BY (COUNTRY_REGION, DATE);

-- 3. Attempting a dynamic table directly inside the shared database also
--    fails, with a clearer, Snowflake-specific error:
--    "Creating dynamic_table on shared database 'COVID19_EPIDEMIOLOGICAL_DATA'
--    is not allowed."
CREATE OR REPLACE DYNAMIC TABLE COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.TEST_PROBE
  TARGET_LAG = '1 hour'
  WAREHOUSE = COMPUTE_WH
AS
SELECT COUNTRY_REGION, CASE_TYPE, DATE, SUM(CASES) AS TOTAL_CASES
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
GROUP BY COUNTRY_REGION, CASE_TYPE, DATE;

/* --------------------------------------------------------------------
   The workaround: an owned database can still read FROM the shared
   table. The restriction is on creating objects INSIDE the shared
   database, not on querying it. A Dynamic Table built in an owned
   database, sourced from the shared table, pre-computes the exact
   subregion aggregation established in Task 2 (SUM across counties per
   country/date), so the API stops repeating that aggregation on every
   request.
   -------------------------------------------------------------------- */

CREATE DATABASE IF NOT EXISTS COVID19_ANALYTICS;

-- First attempt used ANY_VALUE() for ISO3166_1, which Snowflake flagged as
-- non-deterministic: "Query contains the function 'ANY_VALUE', but change
-- tracking is not supported on queries with non-deterministic functions."
-- That forces FULL refresh instead of INCREMENTAL. Replacing it with MAX()
-- (a deterministic aggregate) fixes this.
CREATE OR REPLACE DYNAMIC TABLE COVID19_ANALYTICS.PUBLIC.NATIONAL_DAILY_CASES
  TARGET_LAG = '1 hour'
  WAREHOUSE = COMPUTE_WH
AS
SELECT
    COUNTRY_REGION,
    MAX(ISO3166_1) AS ISO3166_1,
    CASE_TYPE,
    DATE,
    SUM(CASES) AS TOTAL_CASES,
    SUM(DIFFERENCE) AS NEW_CASES
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
GROUP BY COUNTRY_REGION, CASE_TYPE, DATE;

-- This table is owned by this account, so a clustering key can be added.
-- Clustered on the exact columns the API filters and sorts by.
--
-- IMPORTANT: CREATE OR REPLACE DYNAMIC TABLE drops any previously set
-- clustering key. If the CREATE OR REPLACE statement above is ever re-run
-- on its own (e.g. to pick up a schema change), this ALTER TABLE statement
-- must be re-run right after it, every time, or the table will silently go
-- back to having no clustering key. Confirmed live: after re-running the
-- CREATE OR REPLACE, SHOW DYNAMIC TABLES showed an empty cluster_by column
-- until this ALTER TABLE was re-applied.
ALTER TABLE COVID19_ANALYTICS.PUBLIC.NATIONAL_DAILY_CASES
  CLUSTER BY (CASE_TYPE, COUNTRY_REGION, DATE);

-- Verification: confirms INCREMENTAL refresh mode and the row-count drop.
SHOW DYNAMIC TABLES LIKE 'NATIONAL_DAILY_CASES' IN SCHEMA COVID19_ANALYTICS.PUBLIC;
SELECT COUNT(*) AS row_count FROM COVID19_ANALYTICS.PUBLIC.NATIONAL_DAILY_CASES;

/* --------------------------------------------------------------------
   Measured result (via INFORMATION_SCHEMA.QUERY_HISTORY, same query,
   same country, same day):

     Before (aggregate JHU_COVID_19 on every request):
       267,457,024 bytes scanned, 249 ms elapsed

     After (read from NATIONAL_DAILY_CASES):
       17,546,752 bytes scanned, 165 ms elapsed

   About 15x less data scanned, and the row count dropped from 9,738,292
   to 604,123 (about 16x fewer rows) after aggregating to one row per
   country / case type / date instead of one row per subregion.
   -------------------------------------------------------------------- */

SELECT
    QUERY_ID,
    BYTES_SCANNED,
    TOTAL_ELAPSED_TIME AS elapsed_ms,
    SUBSTR(QUERY_TEXT, 1, 60) AS query_start
FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY())
WHERE QUERY_TEXT ILIKE '%NATIONAL_DAILY_CASES%'
   OR (QUERY_TEXT ILIKE '%GROUP BY DATE%' AND QUERY_TEXT ILIKE '%JHU_COVID_19%')
ORDER BY START_TIME DESC
LIMIT 10;