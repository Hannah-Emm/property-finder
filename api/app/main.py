from fastapi import FastAPI, Request, Depends
from contextlib import asynccontextmanager
from typing import AsyncIterator
from .db import get_db_connection_pool, db_conn, DBConnection


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_pool = get_db_connection_pool()
    await db_pool.open()
    yield {"db_pool": db_pool}
    await db_pool.close()

app = FastAPI(lifespan=lifespan, dependencies=[Depends(db_conn)])


@app.get("/")
async def read_root(connection: DBConnection):
    async with connection.cursor() as cursor:
        await cursor.execute("select * from properties")
        return await cursor.fetchone()
