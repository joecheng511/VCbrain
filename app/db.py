"""psycopg2 connection pool with a context-managed checkout helper."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator, Optional

import psycopg2
from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from .config import settings

_pool: Optional[ThreadedConnectionPool] = None
_pool_lock = threading.Lock()


def init_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:  # double-checked locking
                _pool = ThreadedConnectionPool(
                    minconn=settings.db_pool_min,
                    maxconn=settings.db_pool_max,
                    dsn=settings.database_url,
                )
    return _pool


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.closeall()
            _pool = None


@contextmanager
def get_conn() -> Iterator[PgConnection]:  # type: ignore[return]
    """Check out a connection. Commits on success, rolls back on error."""
    pool = init_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


@contextmanager
def get_dict_cursor() -> Iterator[psycopg2.extensions.cursor]:
    """Convenience wrapper that yields a RealDictCursor."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
