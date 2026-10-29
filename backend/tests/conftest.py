"""
Test bootstrap.

Responsible for: pointing the SQLite ledger at a throwaway in-memory database
before any backend module is imported, so tests never touch the demo ledger.
NOT responsible for: the demo fixtures themselves (see each test module).
"""

import os

# Only files written by the demo touch SQLite; tests use a clean in-memory DB.
os.environ["FRESHROUTE_DB"] = ":memory:"
