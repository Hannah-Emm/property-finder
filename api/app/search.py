from pydantic import BaseModel
from typing import Optional, Annotated
from fastapi import Depends, Request
from .journey import StartType, DayOfWeek
from .db import DBConnection, db_conn_returns
from .property import PropertyFinderInstance, PropertyNearStationSearchRequest, Station, Property, PropertyStationGroup
from .journey import JourneyFinderInstance, JourneyFinder, TrainJourneySearchRequest, JourneySummary, TrainjourneyOptions


class MatchingPropertySearchRequest(PropertyNearStationSearchRequest, TrainjourneyOptions):
    max_journey_time: int
    destination: str


class PropertyStationGroupDetails(PropertyStationGroup):
    journey_summary: JourneySummary


class Search():
    def __init__(self, connection: DBConnection, property_finder: PropertyFinderInstance, journey_finder: JourneyFinderInstance, request: Request):
        self.connection = connection
        self.property_finder = property_finder
        self.journey_finder = journey_finder
        self.request = request

    async def search(self, search_request: MatchingPropertySearchRequest) -> list[PropertyStationGroup]:
        results = []
        print(f"Searching for properties matching {search_request}")
        properties = await self.property_finder.find_properties_near_stations(search_request)
        print(f"Found properties around {len(properties)} stations")
        requests = []
        for group in properties:
            requests.append(TrainJourneySearchRequest(
                origin=group.station.id,
                destination=search_request.destination,
                start_time=search_request.start_time,
                start_type=search_request.start_type,
                return_time=search_request.return_time,
                return_type=search_request.return_type,
                day_of_week=search_request.day_of_week,
                rail_card=search_request.rail_card
            ))
        journeys = await self.journey_finder.batch_search(requests)
        for i in range(len(properties)):
            station = properties[i].station
            journey = journeys[i]
            if journey == None or journey.outbound_details == None or journey.outbound_details.journey_time_details == None:
                continue
            has_acceptable_outbound_jourey = journey.outbound_details.journey_time_details.fastest_time <= search_request.max_journey_time
            has_return_journey = (journey.return_details !=
                                  None and journey.return_details.journey_time_details != None)
            has_acceptable_return_journey = search_request.return_type == StartType.NONE or (
                has_return_journey and journey.return_details.journey_time_details.fastest_time <= search_request.max_journey_time)
            if has_acceptable_outbound_jourey and has_acceptable_return_journey:
                results.append(PropertyStationGroupDetails(
                    station=station, journey_summary=journey, properties=properties[i].properties))
        return results


type SearchInstance = Annotated[Search, Depends(Search)]
