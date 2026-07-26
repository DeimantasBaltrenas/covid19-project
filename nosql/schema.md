# Task 3 — NoSQL Data Model (MongoDB)

## Why MongoDB

The core COVID-19 dataset in Snowflake is fully structured and relational —
every table has a fixed set of columns and a clear grain (country/province,
date, case type). That works well for the case counts and vaccination data
themselves, but it doesn't fit well for the *supplementary* data this project
also needs to support:

- Free-text comments/annotations on specific data points, with an arbitrary
  number of tags
- References to external articles or datasets, each with a variable number
  of related countries and an optional date range

Both of these have a variable, self-contained shape per record and don't
need to be joined against each other at the database level. A document
store fits that better than adding several new normalized SQL tables would.
MongoDB Atlas was used for the actual implementation (free M0 tier, AWS,
Stockholm region).

## Database and collections

Database: `covid19_project`

### `annotations`

Stores user comments/notes tied to a specific country, date, and case type
from the Snowflake dataset.

```json
{
  "_id": ObjectId("..."),
  "country_region": "United States",
  "iso3166_1": "US",
  "date": ISODate("2022-01-10"),
  "case_type": "Confirmed",
  "author": "deimantasbaltrenas",
  "comment_text": "Omicron wave peak in the US.",
  "tags": ["omicron", "peak", "wave"],
  "created_at": ISODate("2026-07-20T10:00:00Z"),
  "updated_at": null
}
```

| Field | Type | Notes |
|---|---|---|
| `country_region` | string | Matches `COUNTRY_REGION` in `JHU_COVID_19` |
| `iso3166_1` | string | ISO country code, used as the join key back to Snowflake |
| `date` | date | Matches the `DATE` column in the Snowflake table |
| `case_type` | string | e.g. `Confirmed`, `Deaths`, `Recovered` |
| `author` | string | Who wrote the annotation |
| `comment_text` | string | Free-text note |
| `tags` | array of strings | Arbitrary length, used for filtering |
| `created_at` / `updated_at` | date / null | Audit fields |

### `external_sources`

Stores references to outside articles, reports, or datasets related to one
or more countries and, optionally, a date range.

```json
{
  "_id": ObjectId("..."),
  "title": "Germany switches to per-state COVID reporting",
  "description": "Article describing the change in reporting granularity.",
  "url": "https://example.com/article",
  "related_countries": ["Germany"],
  "date_range": {
    "start": ISODate("2020-05-13"),
    "end": null
  },
  "added_by": "deimantasbaltrenas",
  "added_at": ISODate("2026-07-20T10:00:00Z")
}
```

| Field | Type | Notes |
|---|---|---|
| `title` | string | Short title of the source |
| `description` | string | What it's about |
| `url` | string | Link to the source |
| `related_countries` | array of strings | One or more countries it relates to |
| `date_range.start` / `date_range.end` | date / null | `end: null` means open-ended / still relevant |
| `added_by` | string | Who added the entry |
| `added_at` | date | When it was added |

## Design choices

- **No fixed schema enforcement at the database level** — MongoDB doesn't
  require it, and the shape of `tags`, `related_countries`, and free text
  fields is expected to vary between records.
- **`iso3166_1` stored redundantly with `country_region`** — the same
  pattern used in the Snowflake side of the project, so annotations can be
  joined back to case data reliably even when country names don't match
  exactly across sources.
- **No embedded relationship between the two collections** — annotations
  and external sources are independent; if a comment needs to reference an
  article, it can store the article's `_id` as a plain reference field
  rather than nesting the whole document.

## Implementation

Connection and collection setup: `nosql/setup_mongodb.py`.
Credentials are loaded from `.env` (`MONGODB_URI`), following the same
pattern used for the Snowflake connection in Task 2.