/* TASK: 2 - DATA EXPLORATION AND ENHANCEMENT */
/* SQL exploration of Snowflake COVID-19 dataset */

/* Check tables in DB COVID19_EPIDEMIOLOGICAL_DATA */
SHOW TABLES IN DATABASE COVID19_EPIDEMIOLOGICAL_DATA;

/* Check metadata table first */
SELECT *
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.METADATA;

/* Inspect structure and sample rows of the main table */
DESCRIBE TABLE COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19;

SELECT *
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
LIMIT 100;

/* Compare row counts and date ranges against the other JHU tables to check for overlap */
SELECT
    'JHU_COVID_19'                  AS table_name,
    COUNT(*)                        AS row_count,
    MIN(DATE)                       AS min_date,
    MAX(DATE)                       AS max_date
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19

UNION ALL

SELECT
    'JHU_COVID_19_TIMESERIES'       AS table_name,
    COUNT(*)                        AS row_count,
    MIN(DATE)                       AS min_date,
    MAX(DATE)                       AS max_date
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19_TIMESERIES

UNION ALL

SELECT
    'JHU_DASHBOARD_COVID_19_GLOBAL' AS table_name,
    COUNT(*)                        AS row_count,
    MIN(LAST_UPDATE_DATE)           AS min_date,
    MAX(LAST_UPDATE_DATE)           AS max_date
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_DASHBOARD_COVID_19_GLOBAL;


/* Row count and date range covered by JHU_COVID_19 */
SELECT
    COUNT(*)                       AS total_rows,
    MIN(DATE)                      AS earliest_date,
    MAX(DATE)                      AS latest_date,
    COUNT(DISTINCT DATE)           AS distinct_dates,
    COUNT(DISTINCT COUNTRY_REGION) AS distinct_countries
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19;


/* How many case types exist and how many rows per type */
SELECT
    CASE_TYPE,
    COUNT(*) AS row_count
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
GROUP BY CASE_TYPE
ORDER BY row_count DESC;


/* Check how many rows are country-level vs subregion-level,
   since summing without this distinction will double count */
SELECT
    COUNT(*)                         AS total_rows,
    COUNT(PROVINCE_STATE)            AS rows_with_province,
    COUNT(*) - COUNT(PROVINCE_STATE) AS rows_without_province
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19;


/* Same country/subregion check but broken down by CASE_TYPE - Deaths/Recovered/Active
   might follow a different reporting pattern than Confirmed */
SELECT
    CASE_TYPE,
    COUNT(*)                         AS total_rows,
    COUNT(PROVINCE_STATE)            AS rows_with_province,
    COUNT(*) - COUNT(PROVINCE_STATE) AS rows_without_province
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
GROUP BY CASE_TYPE;


/* Check for example Germany and US: does it have one NULL-province row for the
   whole country, or is it also split into regions like the US? */
SELECT
    PROVINCE_STATE,
    COUNT(*) AS row_count
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
WHERE COUNTRY_REGION = 'Germany'
  AND CASE_TYPE = 'Confirmed'
GROUP BY PROVINCE_STATE
ORDER BY row_count DESC
LIMIT 10;

SELECT
    PROVINCE_STATE,
    COUNT(*) AS row_count
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
WHERE COUNTRY_REGION = 'United States'
  AND CASE_TYPE = 'Confirmed'
GROUP BY PROVINCE_STATE
ORDER BY row_count DESC
LIMIT 10;


/* Daily new cases per country, derived from the cumulative CASES column -
   needed before any trend/wave analysis since the raw data is cumulative, not daily */
WITH country_daily AS (
    SELECT
        COUNTRY_REGION,
        CASE_TYPE,
        DATE,
        SUM(CASES) AS cumulative_cases
    FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
    GROUP BY COUNTRY_REGION, CASE_TYPE, DATE
)
SELECT
    COUNTRY_REGION,
    CASE_TYPE,
    DATE,
    cumulative_cases,
    cumulative_cases - LAG(cumulative_cases) OVER (
        PARTITION BY COUNTRY_REGION, CASE_TYPE ORDER BY DATE
    ) AS new_cases
FROM country_daily
WHERE COUNTRY_REGION = 'United States'
  AND CASE_TYPE = 'Confirmed'
ORDER BY DATE DESC
LIMIT 30;


/* 7-day rolling average of new cases, to smooth out day-of-week reporting noise
   and see the underlying trend more clearly */
WITH country_daily AS (
    SELECT
        COUNTRY_REGION,
        CASE_TYPE,
        DATE,
        SUM(CASES) AS cumulative_cases
    FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
    GROUP BY COUNTRY_REGION, CASE_TYPE, DATE
),
daily_new AS (
    SELECT
        *,
        cumulative_cases - LAG(cumulative_cases) OVER (
            PARTITION BY COUNTRY_REGION, CASE_TYPE ORDER BY DATE
        ) AS new_cases
    FROM country_daily
)
SELECT
    COUNTRY_REGION,
    CASE_TYPE,
    DATE,
    new_cases,
    AVG(new_cases) OVER (
        PARTITION BY COUNTRY_REGION, CASE_TYPE ORDER BY DATE
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS new_cases_7day_avg
FROM daily_new
WHERE COUNTRY_REGION = 'United States'
  AND CASE_TYPE = 'Confirmed'
ORDER BY DATE DESC
LIMIT 30;


/* Which date had the highest single-day new case count per country - locates the peak of each wave */
WITH country_daily AS (
    SELECT
        COUNTRY_REGION,
        CASE_TYPE,
        DATE,
        SUM(CASES) AS cumulative_cases
    FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
    WHERE CASE_TYPE = 'Confirmed'
    GROUP BY COUNTRY_REGION, CASE_TYPE, DATE
),
daily_new AS (
    SELECT
        *,
        cumulative_cases - LAG(cumulative_cases) OVER (
            PARTITION BY COUNTRY_REGION, CASE_TYPE ORDER BY DATE
        ) AS new_cases
    FROM country_daily
)
SELECT
    COUNTRY_REGION,
    DATE       AS peak_date,
    new_cases  AS peak_new_cases
FROM daily_new
QUALIFY ROW_NUMBER() OVER (PARTITION BY COUNTRY_REGION ORDER BY new_cases DESC) = 1
ORDER BY peak_new_cases DESC
LIMIT 20;


/* Case fatality rate (deaths / confirmed) per country as of the latest date - which
   countries have the highest fatality rate relative to their confirmed case count */
SELECT
    c.COUNTRY_REGION,
    c.cumulative_cases AS confirmed,
    d.cumulative_cases AS deaths,
    ROUND(d.cumulative_cases / NULLIF(c.cumulative_cases, 0) * 100, 2) AS case_fatality_rate_pct
FROM (
    SELECT
        COUNTRY_REGION,
        DATE,
        SUM(CASES) AS cumulative_cases
    FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
    WHERE CASE_TYPE = 'Confirmed'
    GROUP BY COUNTRY_REGION, DATE
) c
JOIN (
    SELECT
        COUNTRY_REGION,
        DATE,
        SUM(CASES) AS cumulative_cases
    FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
    WHERE CASE_TYPE = 'Deaths'
    GROUP BY COUNTRY_REGION, DATE
) d
    ON c.COUNTRY_REGION = d.COUNTRY_REGION
   AND c.DATE = d.DATE
WHERE c.DATE = (SELECT MAX(DATE) FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19)
  AND c.cumulative_cases > 0
ORDER BY case_fatality_rate_pct DESC
LIMIT 20;


/* Top 20 countries by total confirmed cases as of the latest date - absolute burden */
SELECT
    COUNTRY_REGION,
    SUM(CASES) AS total_confirmed
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
WHERE CASE_TYPE = 'Confirmed'
  AND DATE = (SELECT MAX(DATE) FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19)
GROUP BY COUNTRY_REGION
ORDER BY total_confirmed DESC
LIMIT 20;


/* Month-over-month growth rate of confirmed cases per country - is the spread accelerating or slowing.
   Cases must be summed across provinces per date first, then maxed per month - taking MAX(CASES)
   directly would only capture the single largest province's total, not the national total. */
WITH national_daily AS (
    SELECT
        COUNTRY_REGION,
        DATE,
        SUM(CASES) AS cumulative_cases
    FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
    WHERE CASE_TYPE = 'Confirmed'
    GROUP BY COUNTRY_REGION, DATE
),
monthly AS (
    SELECT
        COUNTRY_REGION,
        DATE_TRUNC('month', DATE) AS month,
        MAX(cumulative_cases)     AS cumulative_cases
    FROM national_daily
    GROUP BY COUNTRY_REGION, DATE_TRUNC('month', DATE)
)
SELECT
    COUNTRY_REGION,
    month,
    cumulative_cases,
    LAG(cumulative_cases) OVER (PARTITION BY COUNTRY_REGION ORDER BY month) AS prev_month_cases,
    ROUND(
        (cumulative_cases - LAG(cumulative_cases) OVER (PARTITION BY COUNTRY_REGION ORDER BY month))
        / NULLIF(LAG(cumulative_cases) OVER (PARTITION BY COUNTRY_REGION ORDER BY month), 0) * 100, 2
    ) AS mom_growth_pct
FROM monthly
WHERE COUNTRY_REGION = 'United States'
ORDER BY month;


/* Check for NULLs in the key columns */
SELECT
    SUM(CASE WHEN COUNTRY_REGION IS NULL THEN 1 ELSE 0 END) AS null_country,
    SUM(CASE WHEN DATE IS NULL THEN 1 ELSE 0 END)            AS null_date,
    SUM(CASE WHEN CASE_TYPE IS NULL THEN 1 ELSE 0 END)       AS null_case_type,
    SUM(CASE WHEN CASES IS NULL THEN 1 ELSE 0 END)           AS null_cases
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19;


/* Look for duplicate rows at the true grain of the data (country/province/FIPS/date/case_type).
   FIPS must be included - grouping without it flags every US state's multiple counties as
   "duplicates" of each other, since they legitimately share the same state name and date. */
SELECT
    COUNTRY_REGION,
    PROVINCE_STATE,
    FIPS,
    DATE,
    CASE_TYPE,
    COUNT(*) AS dup_count
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
GROUP BY COUNTRY_REGION, PROVINCE_STATE, FIPS, DATE, CASE_TYPE
HAVING COUNT(*) > 1
LIMIT 20;


/* Check for negative CASES values */
SELECT
    CASE_TYPE,
    COUNT(*)       AS negative_rows,
    MIN(CASES)     AS most_negative_value
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
WHERE CASES < 0
GROUP BY CASE_TYPE;


/* Check for cumulative case counts that decrease day over day (data revisions) */
WITH country_daily AS (
    SELECT
        COUNTRY_REGION,
        CASE_TYPE,
        DATE,
        SUM(CASES) AS cumulative_cases
    FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
    GROUP BY COUNTRY_REGION, CASE_TYPE, DATE
)
SELECT
    COUNTRY_REGION,
    CASE_TYPE,
    DATE,
    LAG(cumulative_cases) OVER (PARTITION BY COUNTRY_REGION, CASE_TYPE ORDER BY DATE) AS prev_day_cases,
    cumulative_cases AS current_day_cases
FROM country_daily
QUALIFY cumulative_cases < LAG(cumulative_cases) OVER (PARTITION BY COUNTRY_REGION, CASE_TYPE ORDER BY DATE)
ORDER BY DATE DESC
LIMIT 50;


/* Check for gaps in the reporting dates per country/case_type */
WITH country_dates AS (
    SELECT DISTINCT
        COUNTRY_REGION,
        CASE_TYPE,
        DATE
    FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
)
SELECT
    COUNTRY_REGION,
    CASE_TYPE,
    MIN(DATE)                                          AS first_date,
    MAX(DATE)                                          AS last_date,
    COUNT(*)                                           AS actual_reporting_days,
    DATEDIFF(day, MIN(DATE), MAX(DATE)) + 1             AS expected_reporting_days,
    DATEDIFF(day, MIN(DATE), MAX(DATE)) + 1 - COUNT(*)  AS missing_days
FROM country_dates
GROUP BY COUNTRY_REGION, CASE_TYPE
HAVING missing_days > 0
ORDER BY missing_days DESC
LIMIT 20;


/* Inspect DEMOGRAPHICS table structure and sample data */
DESCRIBE TABLE COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.DEMOGRAPHICS;

SELECT *
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.DEMOGRAPHICS
LIMIT 20;


/* Test if FIPS can be used to join JHU COVID data to DEMOGRAPHICS (US county population data) -
   if this returns 0 or very few rows, the FIPS formats don't match and need fixing before this join can be used */
SELECT COUNT(*) AS matched_rows
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19 j
JOIN COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.DEMOGRAPHICS d
    ON j.FIPS = d.FIPS
WHERE j.COUNTRY_REGION = 'United States';


/* Sample FIPS values from both sides to inspect formatting differences */
SELECT DISTINCT FIPS
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
WHERE COUNTRY_REGION = 'United States'
  AND FIPS IS NOT NULL
LIMIT 10;

SELECT DISTINCT FIPS
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.DEMOGRAPHICS
LIMIT 10;


/* Check OWID_VACCINATIONS columns - candidate for enrichment */
DESCRIBE TABLE COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.OWID_VACCINATIONS;


/* Confirm OWID_VACCINATIONS country names actually match JHU_COVID_19 country names -
   a silent mismatch here would cause the enrichment join to quietly drop rows without erroring */
SELECT COUNT(DISTINCT v.COUNTRY_REGION) AS vax_countries_matched
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.OWID_VACCINATIONS v
JOIN (
    SELECT DISTINCT COUNTRY_REGION
    FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
) j
    ON v.COUNTRY_REGION = j.COUNTRY_REGION;


/* List the countries that don't match, so naming mismatches can be fixed before joining */
SELECT DISTINCT v.COUNTRY_REGION AS unmatched_vaccination_country
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.OWID_VACCINATIONS v
LEFT JOIN (
    SELECT DISTINCT COUNTRY_REGION
    FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
) j
    ON v.COUNTRY_REGION = j.COUNTRY_REGION
WHERE j.COUNTRY_REGION IS NULL
ORDER BY 1;


/* One-shot summary of the key data-quality checks above - rerun this after any fix */
SELECT
    COUNT(*)                                                                AS total_rows,
    COUNT(DISTINCT COUNTRY_REGION)                                         AS distinct_countries,
    MIN(DATE)                                                               AS earliest_date,
    MAX(DATE)                                                               AS latest_date,
    SUM(CASE WHEN COUNTRY_REGION IS NULL THEN 1 ELSE 0 END)                AS null_country_rows,
    SUM(CASE WHEN CASES < 0 THEN 1 ELSE 0 END)                             AS negative_case_rows,
    SUM(CASE WHEN FIPS IS NULL AND COUNTRY_REGION = 'United States' THEN 1 ELSE 0 END) AS us_rows_missing_fips
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19;