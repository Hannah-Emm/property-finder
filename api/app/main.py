from fastapi import FastAPI, Depends
from contextlib import asynccontextmanager
from typing import AsyncIterator, Annotated
from .db import get_db_connection_pool
from .property import PropertySearchRequest, Property, PropertyFinderInstance


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_pool = get_db_connection_pool()
    await db_pool.open()
    yield {"db_pool": db_pool}
    await db_pool.close()

app = FastAPI(lifespan=lifespan)


@app.post("/search/near-stations", response_model=dict[Annotated[str, "Station ID"], list[Property]])
async def search_near_stations(search_request: PropertySearchRequest, property_finder: PropertyFinderInstance):
    return await property_finder.find_properties_near_stations(search_request)
