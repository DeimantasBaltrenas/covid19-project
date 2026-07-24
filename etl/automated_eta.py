import snowflake.connector
import pandas as pd
from ydata_profiling import ProfileReport  # automated EDA report generator

# --- Connect to Snowflake ---
conn = snowflake.connector.connect(
    user='YOUR_USER',
    password='YOUR_PASSWORD',
    account='YOUR_ACCOUNT',
    warehouse='COMPUTE_WH',
    database='COVID19_EPIDEMIOLOGICAL_DATA',
    schema='PUBLIC'
)

# --- Pull country-level confirmed cases (avoid double counting subregions) ---
query = """
SELECT COUNTRY_REGION, DATE, CASES, DIFFERENCE
FROM JHU_COVID_19
WHERE CASE_TYPE = 'Confirmed' AND PROVINCE_STATE IS NULL
"""
df_cases = pd.read_sql(query, conn)

# --- Pull vaccination data for enrichment ---
query_vax = """
SELECT COUNTRY_REGION, DATE, PEOPLE_FULLY_VACCINATED_PER_HUNDRED
FROM OWID_VACCINATIONS
"""
df_vax = pd.read_sql(query_vax, conn)

# --- Merge internal Snowflake data ---
df_merged = df_cases.merge(df_vax, on=['COUNTRY_REGION', 'DATE'], how='left')

# --- Bring in external Kaggle dataset for country-level demographics/economics ---
# (DEMOGRAPHICS table only covers US counties, so global enrichment needs an external source)
df_kaggle = pd.read_csv('kaggle_country_demographics.csv')  # e.g. population, GDP, median age

df_enriched = df_merged.merge(
    df_kaggle, 
    left_on='COUNTRY_REGION', 
    right_on='country_name', 
    how='left'
)

# --- Automated EDA ---
profile = ProfileReport(df_enriched, title="COVID-19 Enriched Dataset EDA", minimal=True)
profile.to_file("covid19_eda_report.html")

conn.close()