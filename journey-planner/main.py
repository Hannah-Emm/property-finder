import psycopg
from journey import TrainJourneySearchRequest, TrainJourneySearchResponse, JourneyFinder, DayOfWeek, StartType
from property import PropertySearchRequest, PropertySearchResponse, Property, Station, PropertyFinder

if __name__ == "__main__":
    print("start")
    with psycopg.connect("dbname=db host=db user=admin password=admin") as connection:
        print("connected")
        property_finder = PropertyFinder(connection)
        properties_by_station = property_finder.search(PropertySearchRequest(
            1200, 2000, (-0.08520316157833625, 51.519510935879914)))
        journey_finder = JourneyFinder(connection)
        for station, properties in properties_by_station.results.items():
            print(
                f"{len(properties)} properties found by {station.name}. Checking travel time...")
            journey_details = journey_finder.search(TrainJourneySearchRequest(
                station.id, "182", "09:15:00", StartType.ARRIVE, "17:30:00", StartType.DEPART, DayOfWeek.TUE, "YNG"))
            if journey_details != None:
                print(journey_details.get_journey_summary())
            else:
                print("No journeys found!")
