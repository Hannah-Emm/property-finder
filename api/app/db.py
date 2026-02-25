from psycopg import Connection
from psycopg_pool import AsyncConnectionPool
from fastapi import Request, Depends
from typing import AsyncGenerator, Annotated, Any
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


async def db_execute(connection: Connection, sql: str, args: list[Any] | None = None) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute(sql, args)


async def db_fetch_one(connection: Connection, sql: str, args: list[Any] | None = None) -> tuple[Any, ...] | None:
    async with connection.cursor() as cursor:
        await cursor.execute(sql, args)
        return await cursor.fetchone()


async def db_fetch_all(connection: Connection, sql: str, args: list[Any] | None = None) -> list[tuple[Any, ...]]:
    async with connection.cursor() as cursor:
        await cursor.execute(sql, args)
        return await cursor.fetchall()

type DBConnection = Annotated[Connection, Depends(db_conn)]
