"""main.py — COVID-19 platform API.

Exposes Snowflake case/vaccination data and MongoDB annotations/external
sources through a single FastAPI application. Run with:

    uvicorn api.main:app --reload
"""

from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from api.mongo_client import get_db
from api.snowflake_client import run_query

app = FastAPI(
    title="COVID-19 Platform API",
    description="Query Snowflake case/vaccination data and MongoDB annotations.",
)


# --- Pydantic models ------------------------------------------------------

class AnnotationCreate(BaseModel):
    country_region: str
    iso3166_1: str
    date: date
    case_type: str = "Confirmed"
    author: str
    comment_text: str
    tags: list[str] = []


class ExternalSourceCreate(BaseModel):
    title: str
    description: str
    url: str
    related_countries: list[str] = []
    date_range_start: Optional[date] = None
    date_range_end: Optional[date] = None
    added_by: str


# --- Snowflake endpoints ---------------------------------------------------

@app.get("/countries")
def list_countries():
    """Distinct countries available in the case dataset, with their ISO codes."""
    rows = run_query(
        """
        SELECT DISTINCT COUNTRY_REGION, ANY_VALUE(ISO3166_1) AS ISO3166_1
        FROM JHU_COVID_19
        GROUP BY COUNTRY_REGION
        ORDER BY COUNTRY_REGION
        """
    )
    return rows


@app.get("/cases")
def get_cases(
    country: str = Query(..., description="Value of COUNTRY_REGION, e.g. 'United States'"),
    case_type: str = Query("Confirmed", description="Confirmed, Deaths, or Recovered"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
):
    """
    National daily case totals, aggregated correctly across subregions.

    Some countries (e.g. the US) report at the county level, so a naive
    query grouped only by country and date returns one row per subregion.
    This endpoint sums across subregions first, as established in Task 2.
    """
    sql = """
        SELECT
            DATE,
            SUM(CASES)      AS CASES,
            SUM(DIFFERENCE) AS NEW_CASES
        FROM JHU_COVID_19
        WHERE COUNTRY_REGION = %(country)s
          AND CASE_TYPE = %(case_type)s
    """
    params = {"country": country, "case_type": case_type}
    if start_date:
        sql += " AND DATE >= %(start_date)s"
        params["start_date"] = start_date
    if end_date:
        sql += " AND DATE <= %(end_date)s"
        params["end_date"] = end_date
    sql += " GROUP BY DATE ORDER BY DATE"

    rows = run_query(sql, params)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No data found for country '{country}'")
    return rows


@app.get("/cases/rolling-average")
def get_cases_rolling_average(
    country: str = Query(..., description="Value of COUNTRY_REGION"),
    case_type: str = Query("Confirmed"),
    window: int = Query(7, ge=1, le=30, description="Rolling window size in days"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
):
    """
    Same daily case series as /cases, with a rolling average computed
    on the fly in the API layer rather than stored in Snowflake.
    """
    rows = get_cases(country=country, case_type=case_type, start_date=start_date, end_date=end_date)
    df = pd.DataFrame(rows)
    df["ROLLING_AVG_NEW_CASES"] = df["NEW_CASES"].rolling(window=window, min_periods=1).mean()
    return df.to_dict(orient="records")


@app.get("/vaccinations")
def get_vaccinations(
    country: str = Query(..., description="Value of COUNTRY_REGION"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
):
    sql = """
        SELECT DATE, PEOPLE_FULLY_VACCINATED_PER_HUNDRED
        FROM OWID_VACCINATIONS
        WHERE COUNTRY_REGION = %(country)s
    """
    params = {"country": country}
    if start_date:
        sql += " AND DATE >= %(start_date)s"
        params["start_date"] = start_date
    if end_date:
        sql += " AND DATE <= %(end_date)s"
        params["end_date"] = end_date
    sql += " ORDER BY DATE"

    rows = run_query(sql, params)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No vaccination data found for country '{country}'")
    return rows


# --- MongoDB endpoints -----------------------------------------------------

@app.get("/annotations")
def list_annotations(
    country: Optional[str] = None,
    case_type: Optional[str] = None,
):
    query = {}
    if country:
        query["country_region"] = country
    if case_type:
        query["case_type"] = case_type

    db = get_db()
    docs = list(db["annotations"].find(query, {"_id": 0}))
    return docs


@app.post("/annotations", status_code=201)
def create_annotation(annotation: AnnotationCreate):
    db = get_db()
    doc = annotation.model_dump()
    doc["date"] = datetime.combine(annotation.date, datetime.min.time(), tzinfo=timezone.utc)
    doc["created_at"] = datetime.now(timezone.utc)
    doc["updated_at"] = None
    result = db["annotations"].insert_one(doc)
    return {"inserted_id": str(result.inserted_id)}


@app.get("/external-sources")
def list_external_sources(country: Optional[str] = None):
    query = {}
    if country:
        query["related_countries"] = country

    db = get_db()
    docs = list(db["external_sources"].find(query, {"_id": 0}))
    return docs


@app.post("/external-sources", status_code=201)
def create_external_source(source: ExternalSourceCreate):
    db = get_db()
    doc = {
        "title": source.title,
        "description": source.description,
        "url": source.url,
        "related_countries": source.related_countries,
        "date_range": {
            "start": source.date_range_start,
            "end": source.date_range_end,
        },
        "added_by": source.added_by,
        "added_at": datetime.now(timezone.utc),
    }
    result = db["external_sources"].insert_one(doc)
    return {"inserted_id": str(result.inserted_id)}