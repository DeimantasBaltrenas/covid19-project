"""mongo_client.py — Shared MongoDB connection helper for the API.

Credentials are loaded from a local .env file (via python-dotenv), which is
excluded from Git via .gitignore. See .env.example for the required keys.
"""

import os

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.database import Database

load_dotenv()

_client: MongoClient | None = None


def get_db() -> Database:
    global _client
    if _client is None:
        _client = MongoClient(os.environ['MONGODB_URI'])
    return _client['covid19_project']
