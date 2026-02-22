import psycopg

class PropertySearchRequest():
    def __init__(self, max_price : int, max_station_distance : int, point_of_interest : tuple[float, float]):
        self.max_price = max_price
        self.max_station_distance = max_station_distance
        self.point_of_interest = point_of_interest

class Property():
    def __init__(self, id : str, location : tuple[float, float], address : str, price : int, bedrooms : int, bathrooms : int):
        self.id = id
        self.location = location
        self.address = address
        self.price = price
        self.bedrooms = bedrooms
        self.bathrooms = bathrooms
    
    def __repr__(self):
        return f"id={self.id}, location={self.location}, address={self.address}, price={self.price}, bedrooms={self.bedrooms}, bathrooms={self.bathrooms}"

class Station():
    def __init__(self, id : str, name : str, location : tuple[float, float]):
        self.id = id
        self.name = name
        self.location = location
    
    def __eq__(self, other):
        return isinstance(other, Station) and self.id == other.id and self.name == other.name and self.location == other.location
    
    def __hash__(self):
        return hash((self.id, self.name, self.location))
    
    def __repr__(self):
        return f"id={self.id}, name={self.name}, location={self.location}"

class PropertySearchResponse():
    def __init__(self, request : PropertySearchRequest, results : dict[Station, list[Property]]):
        self.request = request
        self.results = results

class PropertyFinder():
    def __init__(self, connection : psycopg.Connection):
        self.connection = connection

    def search(self, request : PropertySearchRequest) -> PropertySearchResponse:
        with self.connection.cursor() as cursor:
            cursor.execute("""
                select p.id, ST_X(p.location::geometry), ST_Y(p.location::geometry), address, price, bedrooms, bathrooms, s.id, s.name, ST_X(s.location::geometry), ST_Y(s.location::geometry) from properties as p
                join stations as s on ST_DWithin(p.location, s.location, %s) 
                where p.price <= %s
                order by ST_Distance(p.location, ST_GeogFromText(%s::text)) asc
            """,
            [request.max_station_distance, request.max_price, f"POINT({request.point_of_interest[0]} {request.point_of_interest[1]})"])
            results = {}
            for row in cursor:
                station = Station(row[7], row[8], (row[9], row[10]))
                results.setdefault(station, []).append(Property(row[0], (row[1], row[2]), row[3], row[4], row[5], row[6]))
            return PropertySearchResponse(request, results)