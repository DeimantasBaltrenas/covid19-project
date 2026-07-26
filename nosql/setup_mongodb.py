"""setup_mongodb.py — Connects to the MongoDB Atlas cluster and creates the
collections used for supplementary COVID-19 data (user annotations and
external source references).

Credentials are loaded from a local .env file (via python-dotenv), which is
excluded from Git via .gitignore. See .env.example for the required keys.

Safe to re-run: existing sample records are matched by title/comment_text
before inserting, so running this twice won't create duplicates.
"""

import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.environ['MONGODB_URI'])
db = client['covid19_project']

# --- annotations collection ---------------------------------------------
# User comments/notes tied to a specific country, date, and case type from
# the Snowflake dataset. These reference findings from the Task 2 EDA.
annotations = db['annotations']

annotation_records = [
    {
        "country_region": "United States",
        "iso3166_1": "US",
        "date": datetime(2022, 1, 10, tzinfo=timezone.utc),
        "case_type": "Confirmed",
        "author": "deimantasbaltrenas",
        "comment_text": "Omicron wave peak in the US, identified from the "
                         "rolling 7-day average in the Task 2 analysis.",
        "tags": ["omicron", "peak", "wave"],
        "created_at": datetime.now(timezone.utc),
        "updated_at": None,
    },
    {
        "country_region": "Germany",
        "iso3166_1": "DE",
        "date": datetime(2020, 5, 13, tzinfo=timezone.utc),
        "case_type": "Confirmed",
        "author": "deimantasbaltrenas",
        "comment_text": "Germany switches from single national aggregate "
                         "reporting to full per-Bundesland (province-level) "
                         "reporting around this date.",
        "tags": ["reporting-change", "germany", "granularity"],
        "created_at": datetime.now(timezone.utc),
        "updated_at": None,
    },
    {
        "country_region": "United States",
        "iso3166_1": "US",
        "date": None,
        "case_type": "Confirmed",
        "author": "deimantasbaltrenas",
        "comment_text": "Negative NEW_CASES values found in the enriched "
                         "dataset - confirmed as retroactive data revisions "
                         "rather than a data quality bug.",
        "tags": ["data-quality", "revision", "negative-values"],
        "created_at": datetime.now(timezone.utc),
        "updated_at": None,
    },
]

for record in annotation_records:
    annotations.update_one(
        {"comment_text": record["comment_text"]},
        {"$setOnInsert": record},
        upsert=True,
    )

# --- external_sources collection ----------------------------------------
# References to outside articles/reports/datasets related to specific
# countries or date ranges.
external_sources = db['external_sources']

source_records = [
    {
        "title": "Snowflake Public Data (Free) - World Bank indicators",
        "description": "GDP per capita and population data used to enrich "
                        "the COVID-19 case dataset in Task 2.",
        "url": "https://app.snowflake.com/marketplace",
        "related_countries": [],
        "date_range": {"start": None, "end": None},
        "added_by": "deimantasbaltrenas",
        "added_at": datetime.now(timezone.utc),
    },
    {
        "title": "OWID vaccination dataset",
        "description": "Vaccination coverage data joined against case "
                        "counts in the Task 2 enrichment step.",
        "url": "https://ourworldindata.org/covid-vaccinations",
        "related_countries": [],
        "date_range": {"start": None, "end": None},
        "added_by": "deimantasbaltrenas",
        "added_at": datetime.now(timezone.utc),
    },
]

for record in source_records:
    external_sources.update_one(
        {"title": record["title"]},
        {"$setOnInsert": record},
        upsert=True,
    )

print("Collections created:", db.list_collection_names())
print("annotations count:", annotations.count_documents({}))
print("external_sources count:", external_sources.count_documents({}))

client.close()