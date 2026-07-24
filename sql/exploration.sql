/* TASK: 2 - DATA EXPLORATION AND ENHANCEMENT*/
/* SQL exploration of Snowflake COVID-19 dataset */

/*Check schemas in DB COVID19_EPIDEMIOLOGICAL_DATA*/
SHOW SCHEMAS IN DATABASE COVID19_EPIDEMIOLOGICAL_DATA;
SHOW TABLES IN SCHEMA COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC;

/*Check metadata table first*/
SELECT * FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.METADATA;

/*Inspect structure and sample rows of the main table*/

DESCRIBE TABLE COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19;
SELECT * FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19 LIMIT 100;

/*How many case types exist and how many rows per type*/
SELECT CASE_TYPE, COUNT(*) 
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
GROUP BY CASE_TYPE;

/*Date range covered by dataset*/
SELECT MIN(DATE), MAX(DATE)
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19;

/*Check for NULL countries values*/
SELECT COUNT(*) 
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19 
WHERE COUNTRY_REGION IS NULL;


/*Check how many rows are country-level vs subregion-level,
since summing without this distinction will double count*/
SELECT COUNT(*) AS total, 
       COUNT(PROVINCE_STATE) AS with_province,
       COUNT(*) - COUNT(PROVINCE_STATE) AS null_province
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19;

/*Same country/subregion check but broken down by CASE_TYPE - confirmed was already checked above,
but Deaths/Active/Recovered might follow a different reporting pattern, so aggregation logic
may need to differ per case type*/
SELECT CASE_TYPE, 
       COUNT(*) AS total,
       COUNT(PROVINCE_STATE) AS with_province,
       COUNT(*) - COUNT(PROVINCE_STATE) AS null_province
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
GROUP BY CASE_TYPE;


/* Unique countries in dataset*/
SELECT COUNT(DISTINCT COUNTRY_REGION)
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19;

/*Check for example Germany and US: does it have one NULL-province row for the whole country, or is it also split into regions like the US?*/

SELECT PROVINCE_STATE, COUNT(*) 
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
WHERE COUNTRY_REGION = 'Germany' AND CASE_TYPE = 'Confirmed'
GROUP BY PROVINCE_STATE
ORDER BY COUNT(*) DESC
LIMIT 10;

SELECT PROVINCE_STATE, COUNT(*) 
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
WHERE COUNTRY_REGION = 'United States' AND CASE_TYPE = 'Confirmed'
GROUP BY PROVINCE_STATE
ORDER BY COUNT(*) DESC
LIMIT 10;

/*Inspect DEMOGRAPHICS table structure and sample data*/

DESCRIBE TABLE COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.DEMOGRAPHICS;
SELECT * FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.DEMOGRAPHICS LIMIT 20;

/*Test if FIPS can be used to join JHU COVID data to DEMOGRAPHICS (US county population data) - if this returns 0 or very few rows, the FIPS formats don't match and need fixing before this join can be used*/

SELECT COUNT(*) FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19 j
JOIN COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.DEMOGRAPHICS d ON j.FIPS = d.FIPS
WHERE j.COUNTRY_REGION = 'United States';

/*Look for duplicate rows for the same country/date/case_type*/
/*(SUM() would double count these if present*/

SELECT COUNTRY_REGION, DATE, CASE_TYPE, COUNT(*) AS dup_count
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
WHERE PROVINCE_STATE IS NULL
GROUP BY COUNTRY_REGION, DATE, CASE_TYPE
HAVING COUNT(*) > 1
LIMIT 20;

/*Check for negative CASES values*/
SELECT CASE_TYPE, COUNT(*) AS negative_rows
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
WHERE CASES < 0
GROUP BY CASE_TYPE;

/*Check OWID_VACCINATIONS columns - candidate for enrichment*/
DESCRIBE TABLE COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.OWID_VACCINATIONS;

/*Confirm OWID_VACCINATIONS country names actually match JHU_COVID_19 country names -
a silent mismatch here would cause the enrichment join to quietly drop rows without erroring*/
SELECT COUNT(DISTINCT v.COUNTRY_REGION) AS vax_countries_matched
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.OWID_VACCINATIONS v
JOIN (SELECT DISTINCT COUNTRY_REGION FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19) j
ON v.COUNTRY_REGION = j.COUNTRY_REGION;

/*Check HS_BULK_DATA columns - healthcare capacity data, no direct country key*/
DESCRIBE TABLE COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.HS_BULK_DATA;