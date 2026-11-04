"""PostgreSQL checkpointer for LangGraph thread persistence."""

import logging

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from tripmate.config import Settings

logger = logging.getLogger(__name__)


def create_connection_pool(settings: Settings) -> ConnectionPool:
    """Open a connection pool sized for concurrent planning threads."""
    pool = ConnectionPool(
        conninfo=settings.database_dsn,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
        },
    )
    pool.wait()  # Fail fast at startup when the database is unreachable.
    logger.info("PostgreSQL connection pool ready")
    return pool


def create_checkpointer(pool: ConnectionPool) -> PostgresSaver:
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()
    return checkpointer
