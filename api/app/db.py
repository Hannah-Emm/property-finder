from psycopg import Connection
from psycopg_pool import AsyncConnectionPool
from fastapi import Request, Depends
from typing import AsyncGenerator, Annotated
from os import getenv


def get_conn_str():
    return f"""
    dbname={getenv('POSTGRES_DB')}
    user={getenv('POSTGRES_USER')}
    password={getenv('POSTGRES_PASSWORD')}
    host={getenv('POSTGRES_HOST')}
    """


def get_db_connection_pool() -> AsyncConnectionPool:
    return AsyncConnectionPool(
        conninfo=get_conn_str(), open=False
    )


async def db_conn(request: Request) -> AsyncGenerator[Connection]:
    async with request.state.db_pool.connection() as conn:
        yield conn


type DBConnection = Annotated[Connection, Depends(db_conn)]
