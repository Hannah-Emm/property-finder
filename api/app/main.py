from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from contextlib import asynccontextmanager
from typing import AsyncIterator, Annotated
from .db import get_db_connection_pool, DBConnection
from .property import PropertyNearStationSearchRequest, PropertyFinderInstance, PropertyStationGroup
from .journey import TrainJourneySearchRequest, JourneyFinderInstance, JourneySummary
from .search import MatchingPropertySearchRequest, PropertyStationGroupDetails, SearchInstance
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .tasks import fetch_properties_by_stations
from .user import authenticate_user, create_access_token, Token, Current_User


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_pool = get_db_connection_pool()
    await db_pool.open()
    scheduler = AsyncIOScheduler()
    scheduler.start()
    scheduler.add_job(fetch_properties_by_stations, 'interval', minutes=60, args=[
        db_pool], misfire_grace_time=None)
    yield {"db_pool": db_pool}
    scheduler.shutdown()
    await db_pool.close()

app = FastAPI(lifespan=lifespan)


app.mount("/view", StaticFiles(directory="/code/app/static"), name="static")


@app.get("/")
async def index():
    return RedirectResponse(url="/view/index.html", status_code=308)


@app.post("/search/near-stations", response_model=list[PropertyStationGroup])
async def search_near_stations(search_request: PropertyNearStationSearchRequest, property_finder: PropertyFinderInstance):
    return await property_finder.find_properties_near_stations(search_request)


@app.post("/search/train-journey", response_model=JourneySummary)
async def find_journey(search_request: TrainJourneySearchRequest, journey_finder: JourneyFinderInstance):
    return await journey_finder.get_journey_summary(search_request)


@app.post("/search/find-properties", response_model=list[PropertyStationGroupDetails])
async def find_properties(search_request: MatchingPropertySearchRequest, current_user: Current_User, search: SearchInstance):
    return await search.search(search_request)
@app.post("/auth/token", response_model=Token)
async def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db_connection: DBConnection):
    user = await authenticate_user(db_connection, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=400, detail="Incorrect username or password")
    return create_access_token(user.username)
