"""mongo_client.py — Shared MongoDB connection helper for the API.

Credentials are loaded from a local .env file (via python-dotenv), which is
excluded from Git via .gitignore. See .env.example for the required keys.
"""

import os

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.database import Database

load_dotenv()

# Created once, at module import time (i.e. when the API process starts up,
# on the main thread) rather than lazily on the first request. FastAPI runs
# synchronous endpoint functions in a worker thread pool; creating the
# MongoClient there instead of at startup was causing an SSL handshake
# failure against Atlas on this Windows setup.
_client: MongoClient = MongoClient(os.environ['MONGODB_URI'])


def get_db() -> Database:
    """Returns a connection to the 'covid19_project' database in MongoDB."""
    return _client['covid19_project']
