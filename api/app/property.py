from .db import DBConnection, db_fetch_all
from pydantic import BaseModel
from typing import Optional, Annotated
from fastapi import Depends


class SimplePropertySearchRequest(BaseModel):
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    min_bedrooms: Optional[int] = None
    max_bedrooms: Optional[int] = None
    min_bathrooms: Optional[int] = None
    max_bathrooms: Optional[int] = None


class PropertyNearStationSearchRequest(SimplePropertySearchRequest):
    max_station_distance: int


class Property(BaseModel):
    id: str
    location: tuple[float, float]
    address: str
    price: int
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None


class Station(BaseModel):
    id: str
    name: str
    location: tuple[float, float]


class PropertyFinder():
    _SEARCH_BY_NEAR_STATIONS_QUERY_TEMPLATE = """
                select p.id, ST_X(p.location::geometry), ST_Y(p.location::geometry), address, price, bedrooms, bathrooms, s.id, s.name, ST_X(s.location::geometry), ST_Y(s.location::geometry) from properties as p
                join stations as s on ST_DWithin(p.location, s.location, %(max_station_distance)s) 
                where 
                (%(max_price)s::smallint is null or p.price <= %(max_price)s)
                and (%(min_price)s::smallint is null or p.price >= %(min_price)s)
                and (%(max_bedrooms)s::smallint is null or p.bedrooms <= %(max_bedrooms)s)
                and (%(min_bedrooms)s::smallint is null or p.bedrooms >= %(min_bedrooms)s)
                and (%(max_bathrooms)s::smallint is null or (p.bathrooms is null or p.bathrooms <= %(max_bathrooms)s))
                and (%(min_bathrooms)s::smallint is null or (p.bathrooms is null or p.bathrooms >= %(min_bathrooms)s))
            """

    def __init__(self, connection: DBConnection):
        self.connection = connection

    async def find_properties_near_stations(self, request: PropertyNearStationSearchRequest) -> dict[Annotated[str, "Station ID"], list[Property]]:
        rows = await db_fetch_all(self.connection, PropertyFinder._SEARCH_BY_NEAR_STATIONS_QUERY_TEMPLATE, request.model_dump())
        results = {}
        for row in rows:
            station = Station(id=str(row[7]), name=str(
                row[8]), location=(row[9], row[10]))
            results.setdefault(station.id, []).append(
                Property(id=str(row[0]), location=(row[1], row[2]), address=str(row[3]), price=str(row[4]), bedrooms=row[5], bathrooms=row[6]))
        return results


type PropertyFinderInstance = Annotated[PropertyFinder, Depends(
    PropertyFinder)]
