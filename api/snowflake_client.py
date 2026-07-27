"""snowflake_client.py — Shared Snowflake connection helper for the API.

Credentials are loaded from a local .env file (via python-dotenv), which is
excluded from Git via .gitignore. See .env.example for the required keys.
"""

import os
from contextlib import contextmanager

import snowflake.connector
from dotenv import load_dotenv

load_dotenv()


@contextmanager
def get_connection():
    conn = snowflake.connector.connect(
        user=os.environ['SNOWFLAKE_USER'],
        password=os.environ['SNOWFLAKE_PASSWORD'],
        account=os.environ['SNOWFLAKE_ACCOUNT'],
        warehouse='COMPUTE_WH',
        database='COVID19_EPIDEMIOLOGICAL_DATA',
        schema='PUBLIC',
    )
    try:
        yield conn
    finally:
        conn.close()


def run_query(sql: str, params: dict | None = None) -> list[dict]:
    """Runs a query and returns rows as a list of dicts."""
    with get_connection() as conn:
        with conn.cursor(snowflake.connector.DictCursor) as cur:
            cur.execute(sql, params or {})
            return cur.fetchall()