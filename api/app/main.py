from fastapi import FastAPI, Request, Depends
from contextlib import asynccontextmanager
from typing import AsyncIterator
from .db import get_db_connection_pool, db_conn, DBConnection, db_fetch_all, db_fetch_one


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_pool = get_db_connection_pool()
    await db_pool.open()
    yield {"db_pool": db_pool}
    await db_pool.close()

app = FastAPI(lifespan=lifespan, dependencies=[Depends(db_conn)])


@app.get("/")
async def read_root(connection: DBConnection):
    return await db_fetch_all(connection, "select * from properties where price<=%s", [1200])
