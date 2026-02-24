from fastapi import FastAPI, Depends
from contextlib import asynccontextmanager
from typing import AsyncIterator, Annotated
from .db import get_db_connection_pool, db_conn, DBConnection
from .property import PropertyFinder, PropertySearchRequest, Property


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_pool = get_db_connection_pool()
    await db_pool.open()
    yield {"db_pool": db_pool}
    await db_pool.close()

app = FastAPI(lifespan=lifespan, dependencies=[Depends(db_conn)])


@app.post("/search/near-stations", response_model=dict[Annotated[str, "Station ID"], list[Property]])
async def search_near_stations(search_request: PropertySearchRequest, connection: DBConnection):
    return await PropertyFinder(connection).find_properties_near_stations(search_request)
