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
from .db import DBConnection, db_fetch_one, db_execute_many, db_execute_many_fetch
import aiohttp
import asyncio
import json


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
    journey_time_details: JourneyTimeDetails


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
        "Accept-Encoding": "gzip, deflate",
        "Content-Type": "application/json"
    }
    _DATE_FORMAT = "%Y-%m-%d"
    _GET_CACHED_JOURNEY_QUERY_TEMPLATE = """
            select checked_at, data from journeys 
            where origin=%s and destination=%s and start_time=%s and start_type=%s and return_time=%s and return_type=%s and day_of_week=%s and rail_card=%s
            """
    _GET_CACHED_JOURNEYS_QUERY_TEMPLATE = """
            select origin, destination, to_char(start_time, 'HH24:MI:SS'), start_type, to_char(return_time, 'HH24:MI:SS'), return_type, day_of_week, rail_card, checked_at, data, s.id, s.name, s.location, ST_X(s.location::geometry), ST_Y(s.location::geometry), %s as "search_id"
            from journeys as "j" join stations as "s"
            on s.id=j.origin
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
            await self._cache_journey([(search_request, response)])
        return response

    async def batch_search(self, search_requests: list[TrainJourneySearchRequest]) -> list[TrainJourneySearchResponse | None]:
        response = [None] * len(search_requests)
        found_in_cache = []
        looked_up = []
        not_found = []
        to_cache = []
        request_args = []
        for i in range(len(search_requests)):
            request_args.append([
                i,
                search_requests[i].origin,
                search_requests[i].destination,
                search_requests[i].start_time,
                search_requests[i].start_type,
                search_requests[i].return_time,
                search_requests[i].return_type,
                search_requests[i].day_of_week,
                search_requests[i].rail_card
            ])
        cached_journeys = await db_execute_many_fetch(
            self.connection,
            JourneyFinder._GET_CACHED_JOURNEYS_QUERY_TEMPLATE,
            request_args
        )
        for cached_journey in cached_journeys:
            if cached_journey == None:
                continue
            id = int(cached_journey[15])
            response[id] = self._response_to_summary(TrainJourneySearchResponse(
                checked_at=cached_journey[8], data=cached_journey[9]))
            found_in_cache.append(id)
        async with aiohttp.ClientSession() as session:
            futures = []
            for i in range(len(response)):
                if response[i] != None:
                    continue
                futures.append(asyncio.ensure_future(self._do_post_request(
                    session, JourneyFinder._HEADERS, self._get_journey_api_request_body(search_requests[i]), i)))
            for result in await asyncio.gather(*futures):
                if result[1] == None:
                    not_found.append(result[0])
                    continue
                looked_up.append(result[0])
                to_cache.append((search_requests[result[0]], result[1]))
                response[result[0]] = self._response_to_summary(result[1])

        print(
            f"Found journeys cached={len(found_in_cache)} looked_up={len(looked_up)} not_found={len(not_found)}")
        if to_cache:
            await self._cache_journey(to_cache)
        return response

    async def get_journey_summary(self, search_request: TrainJourneySearchRequest) -> JourneySummary | None:
        journey = await self.search(search_request)
        if journey == None:
            return None
        return self._response_to_summary(journey)

    def _response_to_summary(self, search_response: TrainJourneySearchResponse) -> JourneySummary | None:
        outbound_time_summary = self._get_journey_time_details(
            search_response.data, JourneyDirection.OUTBOUND)
        if outbound_time_summary == None:
            return None
        return_time_summary = self._get_journey_time_details(
            search_response.data, JourneyDirection.RETURN)
        fare_details = self._get_journey_fare_details(search_response.data)
        return JourneySummary(
            outbound_details=JourneyDetails(
                journey_time_details=outbound_time_summary),
            return_details=None if return_time_summary == None else JourneyDetails(
                journey_time_details=return_time_summary),
            fare_details=fare_details)

    async def _do_post_request(self, session: ClientSession, headers: dict[str, str], body: dict, id):
        async with session.post(JourneyFinder._ENDPOINT, headers=headers, json=body) as response:
            if response.status == 400:
                print("Bad request")
                return (id, None)
            elif response.headers["content-type"] != "application/json":
                print("Non JSON response")
                print(await response.text())
                return (id, None)
            return (id, TrainJourneySearchResponse(checked_at=datetime.now(), data=await response.json()))

    def _get_journey_time_details(self, data: dict, direction: JourneyDirection) -> JourneyTimeDetails | None:
        durations = []
        times = []
        min_changes = None
        max_changes = None
        direction_field = "outwardJourneys" if direction == JourneyDirection.OUTBOUND else "inwardJourneys"
        if direction_field not in data:
            return None
        for journey in data[direction_field]:
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

    def _get_journey_fare_details(self, data: dict) -> JourneyFareDetails:
        return_fares = []
        outbound_single_fares = []
        inbound_single_fares = []
        journeys = []
        if "outwardJourneys" in data:
            journeys += data["outwardJourneys"]
        if "inwardJourneys" in data:
            journeys += data["inwardJourneys"]
        for journey in journeys:
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

    def _get_journey_api_request_body(self, search_request: TrainJourneySearchRequest) -> dict:
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

        return api_request_body

    def _get_journey_from_api(self, search_request: TrainJourneySearchRequest) -> TrainJourneySearchResponse | None:
        api_response = requests.post(
            JourneyFinder._ENDPOINT, json=self._get_journey_api_request_body(search_request), headers=JourneyFinder._HEADERS)

        if api_response.status_code == 400:
            print("Bad request for ", search_request)
            return None
        return TrainJourneySearchResponse(checked_at=datetime.now(), data=api_response.json())

    async def _cache_journey(self, journeys: list[tuple[TrainJourneySearchRequest, TrainJourneySearchResponse]]) -> None:
        args = []
        for journey in journeys:
            args.append([
                journey[0].origin,
                journey[0].destination,
                journey[0].start_time,
                journey[0].start_type,
                (journey[0].return_time if journey[0].return_time !=
                 None else "00:00:00"),
                (journey[0].return_type if journey[0].return_time !=
                 None else StartType.NONE),
                journey[0].day_of_week,
                journey[0].rail_card,
                json.dumps(journey[1].data)
            ])
        await db_execute_many(
            self.connection,
            JourneyFinder._CACHE_JOURNEY_QUERY_TEMPLATE,
            args
        )


type JourneyFinderInstance = Annotated[JourneyFinder, Depends(JourneyFinder)]
