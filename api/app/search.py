from pydantic import BaseModel
from typing import Optional, Annotated
from fastapi import Depends
from .journey import StartType, DayOfWeek
from .db import DBConnection
from .property import PropertyFinderInstance, PropertyNearStationSearchRequest, Station, Property
from .journey import JourneyFinderInstance, TrainJourneySearchRequest, JourneySummary, TrainjourneyOptions
import concurrent.futures


class MatchingPropertySearchRequest(PropertyNearStationSearchRequest, TrainjourneyOptions):
    max_journey_time: int
    destination: str


class PropertyGroup(BaseModel):
    station: str
    journey_summary: JourneySummary
    properties: list[Property]


async def check_journey(journey_finder: JourneyFinderInstance, search_request: MatchingPropertySearchRequest, station: str, properties: list[Property]):
    print(
        f"Checking station={station} with {len(properties)} properties in range")
    journey_search_request = TrainJourneySearchRequest(
        origin=station,
        destination=search_request.destination,
        start_time=search_request.start_time,
        start_type=search_request.start_type,
        return_time=search_request.return_time,
        return_type=search_request.return_type,
        day_of_week=search_request.day_of_week,
        rail_card=search_request.rail_card
    )
    journey = await journey_finder.get_journey_summary(journey_search_request)
    if journey == None or journey.outbound_details == None:
        return None
    has_acceptable_outbound_jourey = journey.outbound_details.journey_time_details.fastest_time <= search_request.max_journey_time
    has_return_journey = (journey.return_details !=
                          None and journey.return_details.journey_time_details != None)
    has_acceptable_return_journey = search_request.return_type == StartType.NONE or (
        has_return_journey and journey.return_details.journey_time_details.fastest_time <= search_request.max_journey_time)
    if has_acceptable_outbound_jourey and has_acceptable_return_journey:
        return PropertyGroup(station=station, journey_summary=journey, properties=properties)


class Search():
    def __init__(self, connection: DBConnection, property_finder: PropertyFinderInstance, journey_finder: JourneyFinderInstance):
        self.connection = connection
        self.property_finder = property_finder
        self.journey_finder = journey_finder

    async def search(self, search_request: MatchingPropertySearchRequest) -> list[PropertyGroup]:
        results = []
        print(f"Searching for properties matching {search_request}")
        property_search_request = PropertyNearStationSearchRequest(
            max_price=search_request.max_price, max_station_distance=search_request.max_station_distance)
        properties = await self.property_finder.find_properties_near_stations(property_search_request)
        print(f"Found properties around {len(properties.keys())} stations")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            for future in [executor.submit(check_journey, self.journey_finder, search_request, station, properties[station]) for station in properties.keys()]:
                data = await future.result()
                if data != None:
                    print(f"Found journey for {data.station}")
                    results.append(data)
        return results


type SearchInstance = Annotated[Search, Depends(Search)]
