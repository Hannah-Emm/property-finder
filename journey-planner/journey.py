from enum import Enum
from datetime import datetime
import psycopg
import requests
import json
from datetime import datetime, timedelta


class StartType(Enum):
    DEPART = 0
    ARRIVE = 1


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
            return_time: str,
            return_type: StartType,
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


class TrainJourneySearchResponse():
    request: TrainJourneySearchRequest
    checked_at: datetime
    data: map

    def __init__(self, request: TrainJourneySearchRequest, checked_at: datetime, data: map):
        self.request = request
        self.checked_at = checked_at
        self.data = data


class JourneyFinder():
    ENDPOINT = "https://jpservices.nationalrail.co.uk/journey-planner"
    HEADERS = {
        "Accept-Encoding": "gzip, deflate"
    }
    DATE_FORMAT = "%Y-%m-%d"

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
                               current_week_day)).strftime(JourneyFinder.DATE_FORMAT)
            else:
                search_date = (today + timedelta(days=7 - current_week_day +
                               request.day_of_week.value)).strftime(JourneyFinder.DATE_FORMAT)
            outward_time = f"{search_date}T{request.start_time}Z"
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
                "inwardTime": {"travelTime": inward_time, "type": request.return_type.name},
                "increasedInterchange": "ZERO"
            }

            api_response = requests.post(
                JourneyFinder.ENDPOINT, json=api_request_body, headers=JourneyFinder.HEADERS)
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
                               [request.origin, request.destination, request.start_time, request.start_type, request.return_time, request.return_type, request.day_of_week, request.rail_card, json.dumps(response.data)])
                self.connection.commit()
        return response
