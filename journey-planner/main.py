import requests
import re
import psycopg
from time import sleep
import pprint
from journey import TrainJourneySearchRequest, TrainJourneySearchResponse, JourneyFinder, DayOfWeek, StartType
from property import PropertySearchRequest, PropertySearchResponse, Property, Station, PropertyFinder

ENDPOINT = "https://jpservices.nationalrail.co.uk/journey-planner"
HEADERS = {
    "Accept-Encoding": "gzip, deflate"
}
NON_TRAIN_MODES = ["WALK", "TRANSFER", "UNDERGROUND", "SCHEDULED_BUS"]


def search(origin, destination, arrivalTime, depatureTime, railCard):
    requestBody = {
        "origin": {"crs": origin, "group": False},
        "destination": {"crs": destination, "group": True},
        "outwardTime": {"travelTime": arrivalTime, "type": "ARRIVE"},
        "fareRequestDetails": {
            "passengers": {"adult": 1, "child": 0},
            "fareClass": "ANY",
            "railcards": [] if railCard == None else [{"code": railCard, "count": 1}]
        },
        "directTrains": False,
        "reducedTransferTime": False,
        "onlySearchForSleeper": False,
        "overtakenTrains": True,
        "useAlternativeServices": False,
        "inwardTime": {
            "travelTime": depatureTime, "type": "DEPART"
        },
        "increasedInterchange": "ZERO"
    }
    response = requests.post(ENDPOINT, json=requestBody, headers=HEADERS)
    if response.status_code == 400:
        print("Bad request for ", origin)
        return None
    data = response.json()
    return {
        "outward": parseJourneys(data["outwardJourneys"]),
        "inward": parseJourneys(data["inwardJourneys"])
    }


def parseJourneys(journeysJson):
    journeys = []
    for journey in journeysJson:
        pprint.pp(journey)
        extracted = {
            "duration": None,
            "changes": [],
            "destinationCode": journey["destination"]["crsCode"],
            "destinationName": journey["destination"]["name"],
            "fares": [],
            "depatureTime": journey["timetable"]["scheduled"]["departure"],
            "arrivalTime": journey["timetable"]["scheduled"]["arrival"]
        }

        duration = 0
        for durationPart in journey["duration"].split(" "):
            durationNumber = int(re.match(r'\d+', durationPart)[0])
            if durationPart.endswith("h"):
                duration += durationNumber * 60
            elif durationPart.endswith("m"):
                duration += durationNumber
        extracted["duration"] = duration

        for leg in journey["legs"]:
            change = {
                "startCode": leg["board"]["crsCode"],
                # "startName": leg["board"]["name"],
                "endCode": leg["alight"]["crsCode"],
                # "endName": leg["alight"]["name"],
                "mode": leg["mode"]
            }
            if leg["mode"] not in NON_TRAIN_MODES:
                change["operatorCode"] = leg["operator"]["code"]
                change["operatorName"] = leg["operator"]["name"]
            else:
                change["operatorCode"] = None
                change["operatorName"] = None
            extracted["changes"].append(change)

        for fare in journey["fares"]:
            extracted["fares"].append({
                "price": fare["totalPrice"],
                "type": fare["typeDescription"],
                "direction": fare["direction"]
            })
        journeys.append(extracted)
    return journeys


def getStations(connection):
    with connection.cursor() as cursor:
        stations = []
        cursor.execute("""select id from stations as "s" where not exists (
	        select 1 from journeys as "j" where j.originid=s.id
        ) order by ST_Distance(location, ST_GeogFromText('POINT(-0.08520316157833625 51.519510935879914)')) asc
        """)
        for station in cursor:
            stations.append(station[0])
        return stations


def storeJourneys(connection, journeyType, journeys):
    with connection.cursor() as cursor:
        journeysConverted = []
        for journey in journeys["outward"]:
            journeysConverted.append(
                journeyToArray(journeyType + "Out", journey))
        for journey in journeys["inward"]:
            journeysConverted.append(
                journeyToArray(journeyType + "In", journey))
        cursor.executemany(
            """INSERT INTO journeys (journeytype, duration, changes, originid, destinationid, fares, depaturetime, arrivaltime, checkedat)
            values (%s, %s, %s::trainchange[], %s, %s, %s::fare[], %s, %s, %s)
            """,
            journeysConverted
        )


def journeyToArray(journeyType, journey):
    journeyArray = []
    journeyArray.append(journeyType)
    journeyArray.append(journey["duration"]),
    changes = []
    for change in journey["changes"]:
        changes.append((change["startCode"], change["endCode"],
                       change["operatorCode"], change["operatorName"], change["mode"]))
    journeyArray.append(changes)
    journeyArray.append(journey["changes"][0]["startCode"])
    journeyArray.append(
        journey["changes"][len(journey["changes"])-1]["endCode"])
    fares = []
    for fare in journey["fares"]:
        fares.append((fare["price"], fare["direction"], fare["type"]))
    journeyArray.append(fares)
    journeyArray.append(journey["depatureTime"])
    journeyArray.append(journey["arrivalTime"])
    journeyArray.append("now()")
    return journeyArray


if __name__ == "__main__":
    # pprint.pprint(search("SOC", "182", "2026-02-19T09:15:00Z", "2026-02-19T17:30:00Z", "YNG"))
    print("start")
    with psycopg.connect("dbname=db host=db user=admin password=admin") as connection:
        print("connected")
        request = TrainJourneySearchRequest(
            "SOC", "182", "09:15:00", StartType.ARRIVE, "17:30:00", StartType.DEPART, DayOfWeek.MON, "YNG")
        finder = JourneyFinder(connection)
        print(finder.search(request))

        # property_finder = PropertyFinder(connection)
        # properties_by_station = property_finder.search(PropertySearchRequest(1200, 2000, (-0.08520316157833625, 51.519510935879914)))
        # for station in properties_by_station.results:
        #     print(f"{station} has {len(properties_by_station.results[station])} properties")

        # journey_finder = JourneyFinder(connection)
        # for station, properties in properties_by_station.results.items():
        #     print(f"{len(properties)} properties found by {station.name}. Checking travel time...")
        #     journey_details = journey_finder.search(TrainJourneySearchRequest(station.id, "182", "09:15:00", StartType.ARRIVE, "17:30:00", StartType.DEPART, DayOfWeek.TUE, "YNG"))
        #     pprint.pp(journey_details)

        # search("STQ", "182", "2026-02-26T09:15:00Z", "2026-02-26T17:30:00Z", "YNG")
        # for station in getStations(connection):
        #     print("Checking for " + station)
        #     results = search(station, "182", "2026-02-26T09:15:00Z", "2026-02-26T17:30:00Z", "YNG")
        #     if results != None:
        #         storeJourneys(connection, "work", results)
        #         connection.commit()
