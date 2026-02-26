from enum import Enum
from datetime import datetime
import requests
import json
from datetime import datetime, timedelta
from statistics import mean
import re
from fastapi import Depends
from typing import Annotated, Optional
from pydantic import BaseModel
from .db import DBConnection, db_fetch_one, db_execute


class JourneyDirection(str, Enum):
    OUTBOUND = "OUTBOUND"
    RETURN = "RETURN"


class StartType(str, Enum):
    DEPART = "DEPART"
    ARRIVE = "ARRIVE"
    NONE = "NONE"


class DayOfWeek(Enum):
    SUN = 0
    MON = 1
    TUE = 2
    WED = 3
    THU = 4
    FRI = 5
    SAT = 6


class TrainjourneyOptions(BaseModel):
    start_time: str
    start_type: StartType
    return_time: str | None
    return_type: StartType | None
    day_of_week: DayOfWeek
    rail_card: str

    def is_return_journey(self):
        return self.return_time != None


class TrainJourneySearchRequest(TrainjourneyOptions):
    origin: str
    destination: str


class JourneyTimeDetails(BaseModel):
    fastest_time: int
    average_time: int
    slowest_time: int
    least_changes: int
    most_changes: int
    shortest_wait: int | None = None
    average_wait: int | None = None
    longest_wait: int | None = None


class Fare(BaseModel):
    price: int
    type: str
    direction: str

    def __lt__(self, other):
        return self.price < other.price

    def __gt__(self, other):
        return self.price > other.price


class JourneyFareDetails(BaseModel):
    cheapest_return: Fare | None
    cheapest_single: Optional[list[Fare]] = None


class JourneyDetails(BaseModel):
    journey_time_details: Optional[JourneyTimeDetails] = None


class JourneySummary(BaseModel):
    outbound_details: JourneyDetails
    return_details: Optional[JourneyDetails] = None
    fare_details: JourneyFareDetails


class TrainJourneySearchResponse(BaseModel):
    checked_at: datetime
    data: dict


class JourneyFinder():
    _ENDPOINT = "https://jpservices.nationalrail.co.uk/journey-planner"
    _HEADERS = {
        "Accept-Encoding": "gzip, deflate"
    }
    _DATE_FORMAT = "%Y-%m-%d"
    _GET_CACHED_JOURNEY_QUERY_TEMPLATE = """
            select checked_at, data from journeys 
            where origin=%s and destination=%s and start_time=%s and start_type=%s and return_time=%s and return_type=%s and day_of_week=%s and rail_card=%s
            """
    _CACHE_JOURNEY_QUERY_TEMPLATE = """
            insert into journeys (origin, destination, start_time, start_type, return_time, return_type, day_of_week, rail_card, data)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (origin, destination, start_time, start_type, return_time, return_type, day_of_week, rail_card)
            do update set checked_at=now(), data=excluded.data
            """

    def __init__(self, connection: DBConnection):
        self.connection = connection

    async def search(self, search_request: TrainJourneySearchRequest) -> TrainJourneySearchResponse | None:
        response = await self._get_cached_journey(search_request)
        # if no results fetch from api
        if response == None:
            response = self._get_journey_from_api(search_request)
            if response == None or response.data == None:
                return None
            # update or store in db
            await self._cache_journey(search_request, response)
        return response

    async def get_journey_summary(self, search_request: TrainJourneySearchRequest) -> JourneySummary | None:
        journey = await self.search(search_request)
        if journey == None:
            return None
        return JourneySummary(
            outbound_details=JourneyDetails(
                journey_time_details=self._get_journey_time_details(journey.data, JourneyDirection.OUTBOUND)),
            return_details=JourneyDetails(journey_time_details=None if search_request.return_type ==
                                          StartType.NONE else self._get_journey_time_details(journey.data, JourneyDirection.RETURN)),
            fare_details=self._get_journey_fare_details(
                search_request, journey.data)
        )

    def _get_journey_time_details(self, data: dict, direction: JourneyDirection) -> JourneyTimeDetails:
        durations = []
        times = []
        min_changes = None
        max_changes = None
        for journey in data["outwardJourneys" if direction == JourneyDirection.OUTBOUND else "inwardJourneys"]:
            duration = 0
            for durationPart in journey["duration"].split(" "):
                durationNumber = int(re.match(r'\d+', durationPart)[0])
                if durationPart.endswith("h"):
                    duration += durationNumber * 60
                elif durationPart.endswith("m"):
                    duration += durationNumber
            durations.append(duration)

            times.append(datetime.strptime(
                journey["timetable"]["scheduled"]["departure"], "%Y-%m-%dT%H:%M:%SZ"))

            changes = len(journey["legs"])
            if min_changes == None:
                min_changes = changes
                max_changes = changes
            else:
                min_changes = min(min_changes, changes)
                max_changes = max(max_changes, changes)

        if len(times) > 1:
            wait_times = []
            for i in range(0, len(times)-1, 2):
                wait_times.append(
                    int((times[i+1] - times[i]).total_seconds() / 60))
            return JourneyTimeDetails(
                fastest_time=min(durations),
                average_time=int(mean(durations)),
                slowest_time=max(durations),
                least_changes=min_changes,
                most_changes=max_changes,
                shortest_wait=min(wait_times),
                average_wait=int(mean(wait_times)),
                longest_wait=max(wait_times))
        elif len(times) == 1:
            return JourneyTimeDetails(
                fastest_time=min(durations),
                average_time=int(mean(durations)),
                slowest_time=max(durations),
                least_changes=min_changes,
                most_changes=max_changes)
        else:
            return None

    def _get_journey_fare_details(self, search_request: TrainJourneySearchRequest, data: dict) -> JourneyFareDetails:
        return_fares = []
        outbound_single_fares = []
        inbound_single_fares = []

        for journey in (data["outwardJourneys"] + ([] if not search_request.is_return_journey() else data["inwardJourneys"])):
            for fare in journey["fares"]:
                fare_details = Fare(
                    price=fare["totalPrice"], type=fare["typeDescription"], direction=fare["direction"])
                if fare_details.direction == "RETURN":
                    return_fares.append(fare_details)
                elif fare_details.direction == "OUTWARD":
                    outbound_single_fares.append(fare_details)
                elif fare_details.direction == "INWARD":
                    inbound_single_fares.append(fare_details)

        cheapest_return_fare = None
        if len(return_fares) != 0:
            return_fares.sort()
            cheapest_return_fare = return_fares[0]

        cheapest_single_fares = None
        if len(outbound_single_fares) != 0:
            outbound_single_fares.sort()
            cheapest_single_fares = [outbound_single_fares[0]]
            if len(inbound_single_fares) != 0:
                inbound_single_fares.sort()
                cheapest_single_fares.append(inbound_single_fares[0])

        return JourneyFareDetails(cheapest_return=cheapest_return_fare, cheapest_single=cheapest_single_fares)

    async def _get_cached_journey(self, search_request: TrainJourneySearchRequest) -> TrainJourneySearchResponse | None:
        cached_journey = await db_fetch_one(
            self.connection,
            JourneyFinder._GET_CACHED_JOURNEY_QUERY_TEMPLATE,
            [
                search_request.origin,
                search_request.destination,
                search_request.start_time,
                search_request.start_type,
                search_request.return_time,
                search_request.return_type,
                search_request.day_of_week,
                search_request.rail_card
            ]
        )
        if cached_journey != None:
            return TrainJourneySearchResponse(checked_at=cached_journey[0], data=cached_journey[1])
        return None

    def _get_journey_from_api(self, search_request: TrainJourneySearchRequest) -> TrainJourneySearchResponse | None:
        today = datetime.today()
        current_week_day = today.weekday() + 1 if today.weekday() < 6 else 0
        if current_week_day < search_request.day_of_week.value:
            search_date = (today + timedelta(days=search_request.day_of_week.value -
                                             current_week_day)).strftime(JourneyFinder._DATE_FORMAT)
        else:
            search_date = (today + timedelta(days=7 - current_week_day +
                                             search_request.day_of_week.value)).strftime(JourneyFinder._DATE_FORMAT)
        outward_time = f"{search_date}T{search_request.start_time}Z"
        if search_request.return_time != None:
            inward_time = f"{search_date}T{search_request.return_time}Z"

        api_request_body = {
            # Assume that numerical destinations are groups rather than stations
            # e.g. 182 == Any London station
            # TODO: is there a better way to detect is a station is a group?
            "origin": {"crs": search_request.origin, "group": search_request.origin.isdigit()},
            "destination": {"crs": search_request.destination, "group": search_request.destination.isdigit()},
            "outwardTime": {"travelTime": outward_time, "type": search_request.start_type.name},
            "fareRequestDetails": {
                "passengers": {"adult": 1, "child": 0},
                "fareClass": "ANY",
                "railcards": [] if search_request.rail_card == None else [{"code": search_request.rail_card, "count": 1}]
            },
            "directTrains": False,
            "reducedTransferTime": False,
            "onlySearchForSleeper": False,
            "overtakenTrains": True,
            "useAlternativeServices": False,
            "increasedInterchange": "ZERO"
        }
        if search_request.return_time != None:
            api_request_body["inwardTime"] = {
                "travelTime": inward_time, "type": search_request.return_type.name}

        api_response = requests.post(
            JourneyFinder._ENDPOINT, json=api_request_body, headers=JourneyFinder._HEADERS)

        if api_response.status_code == 400:
            print("Bad request for ", search_request)
            return None
        return TrainJourneySearchResponse(checked_at=datetime.now(), data=api_response.json())

    async def _cache_journey(self, search_request: TrainJourneySearchRequest, search_result: TrainJourneySearchResponse) -> None:
        await db_execute(
            self.connection,
            JourneyFinder._CACHE_JOURNEY_QUERY_TEMPLATE,
            [
                search_request.origin,
                search_request.destination,
                search_request.start_time,
                search_request.start_type,
                (search_request.return_time if search_request.return_time !=
                 None else "00:00:00"),
                (search_request.return_type if search_request.return_time !=
                 None else StartType.NONE),
                search_request.day_of_week,
                search_request.rail_card,
                json.dumps(search_result.data)
            ]
        )


type JourneyFinderInstance = Annotated[JourneyFinder, Depends(JourneyFinder)]
