# COVID-19 Data Integration, Analysis, and Visualization Platform

Data platform that pulls COVID-19 epidemiological data from Snowflake, enriches it with external economic and demographic data, exposes it through an API, and visualizes it through an interactive dashboard, including forecasting and clustering, with supplementary annotations stored in MongoDB.

This README covers what has been built (Tasks 1-10) and reflects finished state of a project.

## About this project

This is a bootcamp assignment for a data engineering bootcamp. An assignment specifies technologies to use (Snowflake, Python, a NoSQL database, a Python visualization library) and a fixed list of tasks to complete, from acquiring dataset through performance optimization and pattern recognition. Goal of a project is to apply what was covered during Bootcamp: querying and modeling data in Snowflake, augmenting it with external sources, designing a NoSQL schema for data that doesn't fit a relational structure, building an API, and visualizing resulst.

Case counts alone don't say much on their own. GDP, population, and vaccination rollout give numbers actual context. Building that context properly meant pulling raw case data from Snowflake, fixing structural issues found in it (reporting granularity varies a lot by country, as explained in the report), enriching it with outside data through a reliable join key, and keeping the whole setup reproducible from a clean checkout, since assignment also requires a solution to run on a machine other than one it was built on.

## Requirements

- **Python 3.11.** `ydata-profiling` (used for automated EDA in Task 2) does not have a compatible build for Python 3.14 at time. If your default Python is newer, install 3.11 separately and point virtual environment at it. With `uv`, that's `uv python install 3.11` followed by `uv venv --python 3.11 venv`.
- A **Snowflake account** with access to `COVID-19 Epidemiological Data` and `Snowflake Public Data (Free)` Marketplace listings (both free). Snowflake is a cloud service, so there is nothing to install locally beyond Python connector.
- A **MongoDB Atlas cluster** (free M0 tier is enough). Also cloud-hosted, nothing to install locally beyond `pymongo`.
- Both services require their own credentials, supplied via `.env` (see [Configuration](#configuration)). This project doesn't and can't bundle access to someone else's Snowflake or Atlas account.

## Quick start

```bash
git clone <repo-url>
cd covid19-project
python -m venv venv
venv\Scripts\activate          # Windows; use `source venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
cp .env.example .env           # then fill in your Snowflake + MongoDB credentials
python etl/automated_eda.py              # pulls, enriches, and profiles data
python nosql/setup_mongodb.py            # sets up MongoDB collections
python -m uvicorn api.main:app --reload  # terminal 1, starts API at http://127.0.0.1:8000/docs
python dashboard/app.py                  # terminal 2, starts dashboard at http://127.0.0.1:8050
```

 API and dashboard are two separate long-running processes and need to run in two separate terminals at the same time. Dashboard has no database credentials of its own and gets all its data from API over HTTP.

### If the wrong Python version gets picked up

`venv\Scripts\activate` has to be run in every new terminal window before running any project command in it, including a second terminal opened for dashboard while API is already running in first one. If it's skipped, Windows can silently fall back to a different, globally installed Python (3.14 in one case seen during testing), and `pandas`/`numpy` either fail to import or take a very long time to do so, since they aren't built for that version the same way. After activating, `python --version` should print `Python 3.11.x`. If it prints something else, virtual environment itself was created with wrong interpreter and needs to be rebuilt: `py -3.11 -m venv venv`, then `venv\Scripts\activate` and `pip install -r requirements.txt` again.

If more than one virtual environment folder exists in a project (for example `venv`, `.venv`, and `.venv-1` left over from earlier setup attempts), always activate same one consistently and consider deleting others, since having several increases a chance of activating a wrong one by mistake in a new terminal.

## What's done

| Task | What it covers
|---|---|---|
| 1 | Snowflake trial account, dataset acquired from Marketplace, resource monitor configured |
| 2 | SQL exploration of dataset, Python enrichment with external data, automated EDA |
| 3 | MongoDB schema for annotations and external source references |
| 4 | FastAPI backend querying Snowflake and MongoDB, with on-fly rolling-average calculation |
| 5 | Dash dashboard (infection rate, mortality rate, vaccination coverage) with annotation bonus feature |
| 6 | Time series forecasting (Holt-Winters) and country clustering bonus (KMeans) |
| 7 | Performance optimization: pre-aggregated Dynamic Table with a clustering key, used by API instead of aggregating raw table on every request |
| 8 | In-memory TTL caching for six most expensive endpoints, with `/cache/stats` and `/cache/clear` for verification |
| 9 | Wave detection via `MATCH_RECOGNIZE`, independently rediscovering Omicron wave already flagged in Tasks 2-3 |
| 10 | All code and configuration pushed to this GitHub repository |

Details on each task, including reasoning behind decisions made, are in [`report/Deimantas_Baltrėnas_Project_Report.pdf`](report/Deimantas_Baltrėnas_Project_Report.pdf).

## How data flows

```
Snowflake Marketplace
  ├─ COVID-19 Epidemiological Data (Starschema)
  └─ Snowflake Public Data Free (GDP, population)
        │
        ▼
  COVID19_EPIDEMIOLOGICAL_DATA (Snowflake, shared, read-only)
        │
        ├──► COVID19_ANALYTICS.PUBLIC.NATIONAL_DAILY_CASES (Dynamic Table, Task 7)
        │       owned, incrementally refreshed, clustered by
        │       (CASE_TYPE, COUNTRY_REGION, DATE)
        │
        ├──► etl/automated_eda.py ──► covid19_eda_report.html
        └──► api/main.py (FastAPI, cached via api/cache.py, Task 8) ──►
                 /countries, /cases, /cases/rolling-average,
                 /vaccinations, /cases/forecast, /clusters
                                              │
MongoDB Atlas (Covid19Cluster)                │
  annotations / external_sources              │
        │                                     │
        ├──► nosql/setup_mongodb.py           │
        └──► api/main.py (FastAPI) ──► /annotations, /external-sources
                                              │
                                              ▼
                                    dashboard/app.py (Dash, HTTP client of API)
```

Dashboard never talks to Snowflake or MongoDB directly. Everything it shows comes through API built in Task 4.

## Tech stack

- Snowflake, for structured data storage and SQL analysis
- Python (`snowflake-connector-python`, `python-dotenv`, `pandas`, `ydata-profiling`, `pymongo`, `fastapi`, `pydantic`, `uvicorn`, `dash`, `plotly`, `requests`, `statsmodels`, `scikit-learn`, `cachetools`), for enrichment, EDA, API, dashboard, and analytical features
- MongoDB Atlas, for supplementary, variable-shaped data

`python-dotenv` loads credentials from `.env` everywhere a Snowflake or MongoDB connection is opened. `pydantic` (installed as a dependency of `fastapi`) validates request bodies for `POST /annotations` and `POST /external-sources`. `plotly` (installed as a dependency of `dash`) is used directly in `dashboard/app.py` to build charts, since Dash itself only provides page layout.

## Project structure

```
.
├── api/
│   ├── main.py                   # FastAPI app and all endpoints
│   ├── cache.py                  # In-memory TTL cache used by @cached (Task 8)
│   ├── snowflake_client.py       # Shared Snowflake connection helper
│   └── mongo_client.py           # Shared MongoDB connection helper
├── dashboard/
│   └── app.py                    # Dash dashboard, calls API over HTTP
├── etl/
│   └── automated_eda.py          # Pulls + enriches Snowflake data, runs automated EDA
├── nosql/
│   ├── schema.md                 # NoSQL schema design and rationale
│   └── setup_mongodb.py          # Creates and populates MongoDB collections
├── sql/
│   ├── exploration.sql           # SQL exploration queries (Task 2)
│   ├── optimization.sql          # Dynamic Table + clustering key setup (Task 7)
│   └── pattern_recognition.sql   # MATCH_RECOGNIZE wave detection (Task 9)
├── report/
│   └── Deimantas_Baltrėnas_Project_Report.pdf
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

`venv` (or `.venv`), `.env`, and `covid19_eda_report.html` are also present locally once project is set up and run, but are not part of repository itself, they're either generated output or gitignored.

## Configuration

Copy `.env.example` to `.env` and fill in:

```
SNOWFLAKE_USER=your_username
SNOWFLAKE_PASSWORD=your_password
SNOWFLAKE_ACCOUNT=your_account_identifier
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/?appName=<app>
```

All four variables are required. `api/mongo_client.py` and `nosql/setup_mongodb.py` both read `MONGODB_URI` at startup and will fail immediately if it's missing.

`.env` is gitignored. Don't commit real credentials. If a credential ever ends up in a commit or chat log, rotate it.

## Running it

- **Resource monitor** (Task 1): run this once against your account, before anything else, to create `COVID19_PROJECT_MONITOR` and attach it to `COMPUTE_WH`. Optional if you already have your own quota controls in place.
  ```sql
  CREATE RESOURCE MONITOR IF NOT EXISTS COVID19_PROJECT_MONITOR
    WITH CREDIT_QUOTA = 50
    FREQUENCY = MONTHLY
    START_TIMESTAMP = IMMEDIATELY
    TRIGGERS
      ON 75 PERCENT DO NOTIFY
      ON 90 PERCENT DO NOTIFY
      ON 100 PERCENT DO SUSPEND
      ON 110 PERCENT DO SUSPEND_IMMEDIATE;

  ALTER WAREHOUSE COMPUTE_WH SET RESOURCE_MONITOR = COVID19_PROJECT_MONITOR;
  ```
  Verify it's attached with `SHOW WAREHOUSES LIKE 'COMPUTE_WH';`.
- **SQL exploration**: run queries in `sql/exploration.sql` against `COVID19_EPIDEMIOLOGICAL_DATA` (Snowflake Worksheet, VS Code extension, or Snowflake CLI, whichever you have set up).
- **Performance optimization**: run `sql/optimization.sql` once to create `COVID19_ANALYTICS` database and `NATIONAL_DAILY_CASES` Dynamic Table the API reads from. Without this, `api/main.py` will fail since it queries that table directly rather than raw `JHU_COVID_19` table.
- **Pattern recognition**: run `sql/pattern_recognition.sql` against `COVID19_ANALYTICS` to build `SMOOTHED_NEW_CASES` table and detect COVID-19 waves per country with `MATCH_RECOGNIZE`. Standalone, not called by the API or dashboard.
- **Data enrichment + automated EDA:**
  ```
  python etl/automated_eda.py
  ```
  Outputs `covid19_eda_report.html`.
- **MongoDB setup:**
  ```
  python nosql/setup_mongodb.py
  ```
  Connects to Atlas cluster and populates `annotations` and `external_sources` collections.
- **API** (terminal 1):
  ```
  python -m uvicorn api.main:app --reload
  ```
  Serves API at `http://127.0.0.1:8000`, with interactive docs at `http://127.0.0.1:8000/docs`. If port 8000 is already taken by something else, run with `--port 8001` (or any other free port) instead. Using `python -m uvicorn ...` instead of bare `uvicorn ...` command avoids issues on systems where `uvicorn` script isn't directly on `PATH`.
- **Dashboard** (terminal 2, with the API already running):
  ```
  python dashboard/app.py
  ```
  Serves dashboard at `http://127.0.0.1:8050`. Pick a country and a date range preset to view infection rate (with a 14-day forecast overlay), mortality rate, and vaccination coverage charts, add or view annotations for that country, and click "Run clustering" to group countries by spread pattern and outcome.
- **Cache diagnostics** (with API running): `GET http://127.0.0.1:8000/cache/stats` returns hit/miss counts and current size. `POST http://127.0.0.1:8000/cache/clear` empties cache, which is only really needed while testing, since it otherwise expires on its own after an hour.

## Data sources

- **COVID-19 Epidemiological Data** (Starschema), from Snowflake Marketplace, a Secure Data Share with no storage cost
- **Snowflake Public Data (Free)**, from Snowflake Marketplace, GDP and population indicators sourced from the World Bank and US Census Bureau
- **OWID Vaccinations**, bundled in primary dataset share

## Known limitations

- Forecast and clustering endpoints fit their models on every request, and results are only kept for up to an hour by the Task 8 cache; for a handful of very small territories with sparse data, `/cases/forecast` may return a 422 error if there isn't enough history to fit a model.
- If `CREATE OR REPLACE DYNAMIC TABLE NATIONAL_DAILY_CASES` in `sql/optimization.sql` is ever re-run on its own, it drops clustering key that was set on that table. Confirmed live: `SHOW DYNAMIC TABLES` showed an empty `cluster_by` column right after a re-run. `ALTER TABLE ... CLUSTER BY` statement in that same script has to be re-run immediately afterward, every time, not just once.
- Reporting granularity varies by country in source data. Some countries report nationally, some subnationally, and this can change mid-pandemic for a given country. This is handled in exploration, enrichment, and API layers, but it's worth keeping in mind when extending queries.
- If MongoDB connections start failing with a TLS/SSL error, check Atlas Network Access first. A dynamic IP change is a more likely cause than an actual code or certificate problem.
- Date-range presets in dashboard are relative to dataset's last recorded date (2023-03-09), not real-world current date.
