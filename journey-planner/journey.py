from enum import Enum
from datetime import datetime
import psycopg
import requests
import json
from datetime import datetime, timedelta
from statistics import mean
import re


class JourneyDirection(Enum):
    OUTBOUND = 0
    RETURN = 1


class StartType(Enum):
    DEPART = 0
    ARRIVE = 1
    NONE = 2


class DayOfWeek(Enum):
    SUN = 0
    MON = 1
    TUE = 2
    WED = 3
    THU = 4
    FRI = 5
    SAT = 6


class TrainJourneySearchRequest():
    def __init__(
            self,
            origin: str,
            destination: str,
            start_time: str,
            start_type: StartType,
            return_time: str | None,
            return_type: StartType | None,
            day_of_week: DayOfWeek,
            rail_card: str):
        self.origin = origin
        self.destination = destination
        self.start_time = start_time
        self.start_type = start_type
        self.return_time = return_time
        self.return_type = return_type
        self.day_of_week = day_of_week
        self.rail_card = rail_card

    def is_return_journey(self):
        return self.return_time != None


class JourneyTimeDetails():
    def __init__(
            self,
            fastest_time: int,
            average_time: int,
            slowest_time: int,
            least_changes: int,
            most_changes: int,
            shortest_wait: int | None = None,
            average_wait: int | None = None,
            longest_wait: int | None = None):
        self.fastest_time = fastest_time
        self.average_time = average_time
        self.slowest_time = slowest_time
        self.least_changes = least_changes
        self.most_changes = most_changes
        self.shortest_wait = shortest_wait
        self.average_wait = average_wait
        self.longest_wait = longest_wait

    def __repr__(self):
        return f"fastest_time={self.fastest_time} average_time={self.average_time} slowest_time={self.average_time} least_changes={self.least_changes} most_changes={self.most_changes} shortest_wait={self.shortest_wait} average_wait={self.average_wait} longest_wait={self.longest_wait}"


class Fare():
    def __init__(self, price: int, type: str, direction: str):
        self.price = price
        self.type = type
        self.direction = direction

    def __lt__(self, other):
        return self.price < other.price

    def __gt__(self, other):
        return self.price > other.price

    def __repr__(self):
        return f"price={self.price} type={self.type} direction={self.direction}"


class JourneyFareDetails():
    def __init__(self, cheapest_return: Fare | None, cheapest_single: list[Fare] | None):
        self.cheapest_return = cheapest_return
        self.cheapest_single = cheapest_single

    def __repr__(self):
        return f"cheapest_return={self.cheapest_return}\ncheapest_single={self.cheapest_single}"


class JourneyDetails():
    def __init__(self, journey_time_details: JourneyTimeDetails):
        self.journey_time_details = journey_time_details

    def __repr__(self):
        return f"times={self.journey_time_details}"


class JourneySummary():
    def __init__(self, outbound_details: JourneyDetails, fare_details: JourneyFareDetails, return_details: JourneyDetails | None = None, ):
        self.outbound_details = outbound_details
        self.fare_details = fare_details
        self.return_details = return_details

    def __repr__(self):
        return f"outbound=({self.outbound_details})\nreturn=({self.return_details})\nfares={self.fare_details}"


class TrainJourneySearchResponse():
    request: TrainJourneySearchRequest
    checked_at: datetime
    data: map

    def __init__(self, request: TrainJourneySearchRequest, checked_at: datetime, data: map):
        self.request = request
        self.checked_at = checked_at
        self.data = data
        self._journey_summary = None

    def get_journey_summary(self) -> JourneySummary:
        if self._journey_summary == None:
            self._journey_suummary = JourneySummary(
                self._get_journey_time_details(JourneyDirection.OUTBOUND),
                self._get_journey_fare_details(),
                None if self.request.return_time == None else self._get_journey_time_details(
                    JourneyDirection.RETURN)
            )
        return self._journey_suummary

    def _get_journey_time_details(self, direction: JourneyDirection) -> JourneyTimeDetails:
        durations = []
        times = []
        min_changes = None
        max_changes = None
        for journey in self.data["outwardJourneys" if direction == JourneyDirection.OUTBOUND else "inwardJourneys"]:
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
                min(durations),
                mean(durations),
                max(durations),
                min_changes,
                max_changes,
                min(wait_times),
                mean(wait_times),
                max(wait_times))
        return JourneyTimeDetails(min(durations), mean(durations), max(durations), min_changes, max_changes)

    def _get_journey_fare_details(self) -> JourneyFareDetails:
        return_fares = []
        outbound_single_fares = []
        inbound_single_fares = []

        for journey in (self.data["outwardJourneys"] + ([] if not self.request.is_return_journey() else self.data["inwardJourneys"])):
            for fare in journey["fares"]:
                fare_details = Fare(
                    fare["totalPrice"], fare["typeDescription"], fare["direction"])
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

        return JourneyFareDetails(cheapest_return_fare, cheapest_single_fares)


class JourneyFinder():
    _ENDPOINT = "https://jpservices.nationalrail.co.uk/journey-planner"
    _HEADERS = {
        "Accept-Encoding": "gzip, deflate"
    }
    _DATE_FORMAT = "%Y-%m-%d"

    def __init__(self, connection: psycopg.Connection):
        self.connection = connection

    def search(self, request: TrainJourneySearchRequest) -> TrainJourneySearchResponse | None:
        response = None

        # get results from db
        with self.connection.cursor() as cursor:
            cursor.execute("""
                select checked_at, data from journeys 
                where origin=%s and destination=%s and start_time=%s and start_type=%s and return_time=%s and return_type=%s and day_of_week=%s and rail_card=%s
            """,
                           [request.origin, request.destination, request.start_time, request.start_type, request.return_time, request.return_type, request.day_of_week, request.rail_card])
            row = cursor.fetchone()
            if row != None:
                response = TrainJourneySearchResponse(request, row[0], row[1])

        # if no results fetch from api
        if response == None:
            today = datetime.today()
            current_week_day = today.weekday() + 1 if today.weekday() < 6 else 0
            if current_week_day < request.day_of_week.value:
                search_date = (today + timedelta(days=request.day_of_week.value -
                               current_week_day)).strftime(JourneyFinder._DATE_FORMAT)
            else:
                search_date = (today + timedelta(days=7 - current_week_day +
                               request.day_of_week.value)).strftime(JourneyFinder._DATE_FORMAT)
            outward_time = f"{search_date}T{request.start_time}Z"
            if request.return_time != None:
                inward_time = f"{search_date}T{request.return_time}Z"
            api_request_body = {
                "origin": {"crs": request.origin, "group": False},
                "destination": {"crs": request.destination, "group": True},
                "outwardTime": {"travelTime": outward_time, "type": request.start_type.name},
                "fareRequestDetails": {
                    "passengers": {"adult": 1, "child": 0},
                    "fareClass": "ANY",
                    "railcards": [] if request.rail_card == None else [{"code": request.rail_card, "count": 1}]
                },
                "directTrains": False,
                "reducedTransferTime": False,
                "onlySearchForSleeper": False,
                "overtakenTrains": True,
                "useAlternativeServices": False,
                "increasedInterchange": "ZERO"
            }
            if request.return_time != None:
                api_request_body["inwardTime"] = {
                    "travelTime": inward_time, "type": request.return_type.name}
            api_response = requests.post(
                JourneyFinder._ENDPOINT, json=api_request_body, headers=JourneyFinder._HEADERS)
            if api_response.status_code == 400:
                print("Bad request for ", request)
                return None
            response = TrainJourneySearchResponse(
                request, datetime.now(), api_response.json())

            # update or store in db
            with self.connection.cursor() as cursor:
                cursor.execute("""
                insert into journeys (origin, destination, start_time, start_type, return_time, return_type, day_of_week, rail_card, data)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (origin, destination, start_time, start_type, return_time, return_type, day_of_week, rail_card)
                do update set checked_at=now(), data=excluded.data
                """,
                               [request.origin, request.destination, request.start_time, request.start_type, (request.return_time if request.return_time != None else "00:00:00"), (request.return_type if request.return_time != None else StartType.NONE), request.day_of_week, request.rail_card, json.dumps(response.data)])
                self.connection.commit()
        return response
