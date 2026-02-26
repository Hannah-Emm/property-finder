from fastapi import FastAPI, Depends
from contextlib import asynccontextmanager
from typing import AsyncIterator, Annotated
from .db import get_db_connection_pool
from .property import PropertyNearStationSearchRequest, Property, PropertyFinderInstance
from .journey import TrainJourneySearchRequest, JourneyFinderInstance, JourneySummary
from .search import MatchingPropertySearchRequest, PropertyGroup, SearchInstance


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_pool = get_db_connection_pool()
    await db_pool.open()
    yield {"db_pool": db_pool}
    await db_pool.close()

app = FastAPI(lifespan=lifespan)


@app.post("/search/near-stations", response_model=dict[Annotated[str, "Station ID"], list[Property]])
async def search_near_stations(search_request: PropertyNearStationSearchRequest, property_finder: PropertyFinderInstance):
    return await property_finder.find_properties_near_stations(search_request)


@app.post("/search/train-journey", response_model=JourneySummary)
async def find_journey(search_request: TrainJourneySearchRequest, journey_finder: JourneyFinderInstance):
    return await journey_finder.get_journey_summary(search_request)


@app.post("/search/find-properties", response_model=list[PropertyGroup])
async def find_properties(search_request: MatchingPropertySearchRequest, search: SearchInstance):
    return await search.search(search_request)
