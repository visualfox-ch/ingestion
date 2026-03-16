"""
Database client compatibility layer.

Re-exports database functions from postgres_state for backward compatibility.
Many services import from app.db_client - this module provides that interface.
"""

from app.postgres_state import get_conn, get_cursor, get_dict_cursor

# Alias for services that expect get_db_client
def get_db_client():
    """Return a database connection (alias for get_conn)."""
    return get_conn()


__all__ = ["get_conn", "get_cursor", "get_dict_cursor", "get_db_client"]
