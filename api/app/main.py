from fastapi import FastAPI, Depends
from contextlib import asynccontextmanager
from typing import AsyncIterator
from .db import get_db_connection_pool, db_conn, DBConnection
from .property import PropertyFinder, PropertySearchRequest, PropertySearchResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_pool = get_db_connection_pool()
    await db_pool.open()
    yield {"db_pool": db_pool}
    await db_pool.close()

app = FastAPI(lifespan=lifespan, dependencies=[Depends(db_conn)])


@app.post("/search/near-stations", response_model=PropertySearchResponse)
async def search_near_stations(search_request: PropertySearchRequest, connection: DBConnection) -> PropertySearchResponse:
    response = await PropertyFinder(connection).find_properties_near_stations(search_request)
    return response
