"""automated_eda.py: pulls COVID-19 case and vaccination data from Snowflake,
enriches it with external demographic/economic data, and generates an
automated EDA report.

Credentials are loaded from a local .env file (via python-dotenv), which is
excluded from Git via .gitignore. See .env.example for the required keys -
copy it to .env and fill in real values before running.
"""

import os

from dotenv import load_dotenv
import snowflake.connector
from ydata_profiling import ProfileReport

load_dotenv()

conn = snowflake.connector.connect(
    user=os.environ['SNOWFLAKE_USER'],
    password=os.environ['SNOWFLAKE_PASSWORD'],
    account=os.environ['SNOWFLAKE_ACCOUNT'],
    warehouse='COMPUTE_WH',
    database='COVID19_EPIDEMIOLOGICAL_DATA',
    schema='PUBLIC'
)

query = """
SELECT COUNTRY_REGION, ANY_VALUE(ISO3166_1) AS ISO3166_1, DATE, SUM(CASES) AS CASES, SUM(DIFFERENCE) AS NEW_CASES
FROM JHU_COVID_19
WHERE CASE_TYPE = 'Confirmed'
GROUP BY COUNTRY_REGION, DATE
"""
with conn.cursor() as cur:
    cur.execute(query)
    df_cases = cur.fetch_pandas_all()

# --- Pull vaccination data for enrichment ---
query_vax = """
SELECT COUNTRY_REGION, DATE, PEOPLE_FULLY_VACCINATED_PER_HUNDRED
FROM OWID_VACCINATIONS
"""
with conn.cursor() as cur:
    cur.execute(query_vax)
    df_vax = cur.fetch_pandas_all()

# --- Merge internal Snowflake data ---
df_merged = df_cases.merge(df_vax, on=['COUNTRY_REGION', 'DATE'], how='left')

query_econ = """
WITH geo AS (
    SELECT GEO_ID, ISO_ALPHA2
    FROM SNOWFLAKE_PUBLIC_DATA_FREE.PUBLIC_DATA_FREE.GEOGRAPHY_INDEX
    WHERE LEVEL = 'Country'
),
gdp AS (
    SELECT GEO_ID, VALUE AS GDP_PER_CAPITA_PPP
    FROM SNOWFLAKE_PUBLIC_DATA_FREE.PUBLIC_DATA_FREE.WORLD_BANK_TIMESERIES
    WHERE VARIABLE = 'WDI_NY.GDP.PCAP.PP.KD'
    QUALIFY ROW_NUMBER() OVER (PARTITION BY GEO_ID ORDER BY DATE DESC) = 1
),
pop AS (
    SELECT GEO_ID, VALUE AS POPULATION_TOTAL
    FROM SNOWFLAKE_PUBLIC_DATA_FREE.PUBLIC_DATA_FREE.WORLD_BANK_TIMESERIES
    WHERE VARIABLE = 'IDS_SP.POP.TOTL'
    QUALIFY ROW_NUMBER() OVER (PARTITION BY GEO_ID ORDER BY DATE DESC) = 1
)
SELECT geo.ISO_ALPHA2, gdp.GDP_PER_CAPITA_PPP, pop.POPULATION_TOTAL
FROM geo
LEFT JOIN gdp ON geo.GEO_ID = gdp.GEO_ID
LEFT JOIN pop ON geo.GEO_ID = pop.GEO_ID
"""
with conn.cursor() as cur:
    cur.execute(query_econ)
    df_econ = cur.fetch_pandas_all()

df_enriched = df_merged.merge(
    df_econ, left_on='ISO3166_1', right_on='ISO_ALPHA2', how='left'
)

unmatched = df_enriched['ISO_ALPHA2'].isna().sum()
total = len(df_enriched)
print(f"Enrichment match: {total - unmatched}/{total} rows matched "
      f"({(total - unmatched) / total:.1%})")
if unmatched > 0:
    print("Unmatched countries:", sorted(
        df_enriched.loc[df_enriched['ISO_ALPHA2'].isna(), 'COUNTRY_REGION'].unique()
    ))

# --- Automated EDA ---
# ydata_profiling generates a word cloud image by default for both
# Categorical columns (vars.cat.words) and Text columns (vars.text.words).
# COUNTRY_REGION and ISO_ALPHA2 are detected as Text type, so both flags
# need to be set to False to remove the word cloud everywhere.
profile = ProfileReport(
    df_enriched,
    title="COVID-19 Enriched Dataset EDA",
    minimal=True,
    vars={
        "cat": {"words": False},
        "text": {"words": False},
    },
)
profile.to_file("covid19_eda_report.html")

conn.close()