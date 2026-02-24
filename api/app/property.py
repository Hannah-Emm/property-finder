from .db import DBConnection, db_fetch_all
from pydantic import BaseModel
from typing import Optional


class PropertySearchRequest(BaseModel):
    max_price: int
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


class PropertySearchResponse(BaseModel):
    request: PropertySearchRequest
    results: dict[str, list[Property]]


class PropertyFinder():
    _SEARCH_BY_NEAR_STATIONS_QUERY_TEMPLATE = """
                select p.id, ST_X(p.location::geometry), ST_Y(p.location::geometry), address, price, bedrooms, bathrooms, s.id, s.name, ST_X(s.location::geometry), ST_Y(s.location::geometry) from properties as p
                join stations as s on ST_DWithin(p.location, s.location, %s) 
                where p.price <= %s
            """

    def __init__(self, connection: DBConnection):
        self.connection = connection

    async def find_properties_near_stations(self, request: PropertySearchRequest) -> PropertySearchResponse:
        args = [request.max_station_distance, request.max_price]
        rows = await db_fetch_all(self.connection, PropertyFinder._SEARCH_BY_NEAR_STATIONS_QUERY_TEMPLATE, args)
        results = {}
        for row in rows:
            station = Station(id=str(row[7]), name=str(row[8]), location=(row[9], row[10]))
            results.setdefault(station.id, []).append(
                Property(id=str(row[0]), location=(row[1], row[2]), address=str(row[3]), price=str(row[4]), bedrooms=row[5], bathrooms=row[6]))
        return PropertySearchResponse(request=request, results=results)
