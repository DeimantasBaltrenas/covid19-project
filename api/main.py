"""main.py — COVID-19 platform API.

Exposes Snowflake case/vaccination data and MongoDB annotations/external
sources through a single FastAPI application. Run with:

    uvicorn api.main:app --reload
"""

from datetime import date, datetime, timezone
import json
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from api.cache import cached, clear_cache, get_cache_stats
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
@cached
def list_countries():
    """Distinct countries available in the case dataset, with their ISO codes.

    Reads from COVID19_ANALYTICS.PUBLIC.NATIONAL_DAILY_CASES (Task 7) instead
    of the raw JHU_COVID_19 table, since the same distinct-country list can be
    read off a table that is about 16x smaller after aggregation.
    """
    rows = run_query(
        """
        SELECT DISTINCT COUNTRY_REGION, MAX(ISO3166_1) AS ISO3166_1
        FROM COVID19_ANALYTICS.PUBLIC.NATIONAL_DAILY_CASES
        GROUP BY COUNTRY_REGION
        ORDER BY COUNTRY_REGION
        """
    )
    return rows


@app.get("/cases")
@cached
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
    That aggregation, established in Task 2, is no longer computed here on
    every request. Instead it is pre-computed once in
    COVID19_ANALYTICS.PUBLIC.NATIONAL_DAILY_CASES, a Dynamic Table that
    incrementally refreshes itself from JHU_COVID_19 (Task 7). This endpoint
    now just filters and sorts a table that is already aggregated and
    clustered by (CASE_TYPE, COUNTRY_REGION, DATE), instead of summing across
    subregions on the fly for every request.
    """
    sql = """
        SELECT
            DATE,
            TOTAL_CASES AS CASES,
            NEW_CASES
        FROM COVID19_ANALYTICS.PUBLIC.NATIONAL_DAILY_CASES
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
    sql += " ORDER BY DATE"

    rows = run_query(sql, params)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No data found for country '{country}'")
    return rows


@app.get("/cases/rolling-average")
@cached
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
    # df.to_dict() leaves NaN as float('nan'), which Starlette's default
    # JSON response rejects ("Out of range float values are not JSON
    # compliant"). pandas' own to_json() serializes NaN as null correctly,
    # so we round-trip through it instead.
    return json.loads(df.to_json(orient="records", date_format="iso"))


@app.get("/vaccinations")
@cached
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


# --- Task 6: analytical features --------------------------------------------

@app.get("/cases/forecast")
@cached
def forecast_cases(
    country: str = Query(..., description="Value of COUNTRY_REGION"),
    horizon_days: int = Query(14, ge=1, le=90, description="Number of days beyond the last recorded date to forecast"),
):
    """
    Forecasts daily new confirmed cases `horizon_days` beyond the last
    date recorded for this country, using Holt-Winters exponential
    smoothing fitted against that country's full historical daily series.
    The result is cached for up to an hour (Task 8), since fitting this
    model on every request is the most expensive operation in the API and
    the underlying data does not change faster than the Dynamic Table's
    own 1-hour refresh cycle (Task 7) anyway.
    """
    rows = get_cases(country=country, case_type="Confirmed", start_date=None, end_date=None)
    df = pd.DataFrame(rows)
    if len(df) < 14:
        raise HTTPException(
            status_code=422,
            detail="Not enough historical data for this country to fit a forecasting model.",
        )

    series = pd.Series(
        df["NEW_CASES"].clip(lower=0).values,
        index=pd.to_datetime(df["DATE"]),
    ).asfreq("D").fillna(0)

    # trend="add" follows the recent upward/downward direction of the
    # series; seasonal_periods=7 captures the weekly reporting pattern
    # (e.g. lower counts reported on weekends) documented in Task 2.
    model = ExponentialSmoothing(
        series,
        trend="add",
        seasonal="add",
        seasonal_periods=7,
        initialization_method="estimated",
    ).fit()
    forecast = model.forecast(horizon_days)

    last_date = series.index.max()
    return [
        {
            "DATE": (last_date + pd.Timedelta(days=i + 1)).date().isoformat(),
            "FORECAST_NEW_CASES": max(0, round(float(value))),
        }
        for i, value in enumerate(forecast)
    ]


@app.get("/clusters")
@cached
def get_country_clusters(n_clusters: int = Query(4, ge=2, le=10)):
    """
    Bonus: groups countries into clusters based on how their COVID-19
    outcomes compare, using three per-capita metrics: total confirmed
    cases per 100k population, peak daily new cases per 100k population,
    and case fatality rate. Population figures come from the same
    Snowflake Public Data (Free) listing used for enrichment in Task 2,
    joined by ISO alpha-2 code for the same reason established there.

    Clustering is computed with scikit-learn's KMeans; no cluster
    assignment is stored in a database. The result is cached for up to an
    hour (Task 8), since re-running KMeans over every country on every
    request is unnecessary work once the underlying totals have already
    been computed for that hour. The confirmed/deaths totals below read
    from COVID19_ANALYTICS.PUBLIC.NATIONAL_DAILY_CASES (Task 7), which is
    already aggregated to one row per country/case type/date, instead of
    re-aggregating JHU_COVID_19 from scratch on every request.
    """
    sql = """
        WITH confirmed_totals AS (
            SELECT
                COUNTRY_REGION,
                MAX(ISO3166_1) AS ISO3166_1,
                MAX(TOTAL_CASES) AS TOTAL_CASES,
                MAX(NEW_CASES)   AS PEAK_NEW_CASES
            FROM COVID19_ANALYTICS.PUBLIC.NATIONAL_DAILY_CASES
            WHERE CASE_TYPE = 'Confirmed'
            GROUP BY COUNTRY_REGION
        ),
        deaths_totals AS (
            SELECT COUNTRY_REGION, MAX(TOTAL_CASES) AS TOTAL_DEATHS
            FROM COVID19_ANALYTICS.PUBLIC.NATIONAL_DAILY_CASES
            WHERE CASE_TYPE = 'Deaths'
            GROUP BY COUNTRY_REGION
        ),
        population AS (
            SELECT geo.ISO_ALPHA2, pop.VALUE AS POPULATION_TOTAL
            FROM SNOWFLAKE_PUBLIC_DATA_FREE.PUBLIC_DATA_FREE.GEOGRAPHY_INDEX geo
            JOIN SNOWFLAKE_PUBLIC_DATA_FREE.PUBLIC_DATA_FREE.WORLD_BANK_TIMESERIES pop
                ON geo.GEO_ID = pop.GEO_ID
            WHERE geo.LEVEL = 'Country' AND pop.VARIABLE = 'IDS_SP.POP.TOTL'
            QUALIFY ROW_NUMBER() OVER (PARTITION BY geo.GEO_ID ORDER BY pop.DATE DESC) = 1
        )
        SELECT
            ct.COUNTRY_REGION,
            ct.ISO3166_1,
            ct.TOTAL_CASES,
            ct.PEAK_NEW_CASES,
            dt.TOTAL_DEATHS,
            p.POPULATION_TOTAL
        FROM confirmed_totals ct
        LEFT JOIN deaths_totals dt ON ct.COUNTRY_REGION = dt.COUNTRY_REGION
        LEFT JOIN population p ON ct.ISO3166_1 = p.ISO_ALPHA2
        WHERE p.POPULATION_TOTAL > 0
    """
    rows = run_query(sql)
    df = pd.DataFrame(rows).dropna(subset=["POPULATION_TOTAL", "TOTAL_CASES"])

    df["CASES_PER_100K"] = df["TOTAL_CASES"] / df["POPULATION_TOTAL"] * 100_000
    df["PEAK_NEW_CASES_PER_100K"] = df["PEAK_NEW_CASES"] / df["POPULATION_TOTAL"] * 100_000
    df["CFR_PERCENT"] = df["TOTAL_DEATHS"].fillna(0) / df["TOTAL_CASES"] * 100

    feature_columns = ["CASES_PER_100K", "PEAK_NEW_CASES_PER_100K", "CFR_PERCENT"]
    # A handful of countries can still end up with a NaN in one of these
    # engineered columns (e.g. no recorded NEW_CASES at all), which KMeans
    # cannot handle — drop those rows rather than letting the whole
    # request fail.
    df = df.dropna(subset=feature_columns)
    # Features are on very different scales (per-100k case counts can be
    # in the tens of thousands; CFR is a small percentage), so they are
    # standardized before clustering — otherwise KMeans would effectively
    # cluster on case counts alone and ignore the fatality rate.
    scaled_features = StandardScaler().fit_transform(df[feature_columns])
    df["CLUSTER"] = KMeans(n_clusters=n_clusters, random_state=42, n_init=10).fit_predict(scaled_features)

    result = df[["COUNTRY_REGION", "ISO3166_1", *feature_columns, "CLUSTER"]]
    return json.loads(result.to_json(orient="records"))


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


# --- Task 8: cache diagnostics ----------------------------------------------

@app.get("/cache/stats")
def cache_stats():
    """Hit/miss counts and current size of the in-memory cache (Task 8).

    Useful for confirming caching is actually working: calling the same
    endpoint with the same parameters twice should increase "hits" by one
    on the second call instead of "misses".
    """
    return get_cache_stats()


@app.post("/cache/clear")
def cache_clear():
    """Empties the cache. Mainly useful during testing/demoing Task 8,
    to force the next request back to a cache miss on demand."""
    clear_cache()
    return {"status": "cache cleared"}