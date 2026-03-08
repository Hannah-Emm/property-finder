from .db import db_execute_many, db_fetch_all
import aiohttp
import asyncio
import time
import polyline
from polycircles import polycircles

_BASE_URL = "https://www.rightmove.co.uk/api/property-search/listing/search"
_PARAMS = {
    "channel": "RENT",
    "transactionType": "LETTING",
    "dontShow": "houseShare,retirement,student"
}
_HEADERS = {
    "Accept-Encoding": "gzip, deflate",
    "Accept": "application/json",
}

_POISON_PILL = "POISON_PILL"
_QUEUE_SIZE = 1000
_BATCH_SIZE = 500


async def _fetch_for_location(session: aiohttp.ClientSession, location: tuple[float, float], max_price: int, output: asyncio.Queue, display_name: str) -> None:
    params = {
        "locationIdentifier": location,
        "channel": "RENT",
        "transactionType": "LETTING",
        "dontShow": "houseShare,retirement,student",
        "maxPrice": max_price
    }
    index = 0
    next = None
    data = None
    async with aiohttp.ClientSession() as session:
        while (index != next):
            if next != None:
                index = next
            params["index"] = index
            async with session.get(_BASE_URL, headers=_HEADERS, params=params) as response:
                if response.status == 503 or response.status == 504:
                    next = None
                    print("Retrying on 503/504")
                    continue
                if "application/json" not in response.headers["content-type"]:
                    print(f"Skipping non json response: {response.url}")
                    return
                data = await response.json()
                if data == None:
                    print(f"Skipping due to no body: {response.url}")
                    return
                if "pagination" in data and "next" in data["pagination"]:
                    next = int(data["pagination"]["next"])
                else:
                    next = index
                if "properties" in data:
                    await output.put(data["properties"])
                if "notFound" in data and data["notFound"]:
                    print(f"Not found: {response.url}")
                    return
    print(f"Finished searching for: {display_name}")


async def _create_worker(queue: asyncio.Queue, db_pool) -> None:
    running = True
    create_start_time = time.time()
    total_processed = 0
    while running:
        batch = []
        while len(batch) < _BATCH_SIZE:
            data = await queue.get()
            if data == _POISON_PILL:
                print("Consumed all queued properties")
                running = False
                async with db_pool.connection() as connection:
                    await _store_properties(connection, batch)
                queue.task_done()
                return
            else:
                batch += data
                queue.task_done()
        async with db_pool.connection() as connection:
            await _store_properties(connection, batch)
        total_processed += len(batch)
        print(
            f"Total_processed={total_processed}, queue_size={queue.qsize()}: Wrote batch with size={len(batch)} in {time.time()-create_start_time} seconds")
        create_start_time = time.time()
        batch = []


def _create_search_polyline(center, radius) -> str:
    polycircle = polycircles.Polycircle(latitude=center[0],
                                        longitude=center[1],
                                        radius=radius,
                                        number_of_vertices=12)
    return polyline.encode(polycircle.to_lat_lon())


async def _store_properties(connection, propertiesJson) -> None:
    if not propertiesJson:
        return
    properties = []
    for property in propertiesJson:
        id = property["id"]
        longitude = property["location"]["longitude"]
        latitude = property["location"]["latitude"]
        location = f"point({longitude} {latitude})"
        address = property["displayAddress"]
        price = property["price"]["amount"]
        if property["price"]["frequency"] == "weekly":
            price = price * 4
        bedrooms = property["bedrooms"]
        bathrooms = property["bathrooms"]
        properties.append([id, location, address, price, bedrooms, bathrooms])

    await db_execute_many(connection,
                          """INSERT INTO properties (id, location, address, price, bedrooms, bathrooms) 
    values (%s, %s, %s, %s, %s, %s) 
    ON CONFLICT(id) DO UPDATE SET 
    location = EXCLUDED.location,
    address = EXCLUDED.address,
    price = EXCLUDED.price,
    bedrooms = EXCLUDED.bedrooms,
    bathrooms = EXCLUDED.bathrooms,
    historic = false
    """,
                          properties)
    await connection.commit()


async def fetch_properties_by_stations(db_pool, max_price=2500, radius=3500) -> None:
    print("Starting property search")
    queue = asyncio.Queue(_QUEUE_SIZE)
    async with aiohttp.ClientSession() as session:
        stations = None
        async with db_pool.connection() as connection:
            stations = await db_fetch_all(connection, "select name, ST_X(location::geometry), ST_Y(location::geometry) from stations")
        tasks = []
        async with asyncio.TaskGroup() as task_group:
            task_group.create_task(_create_worker(queue, db_pool))
            for station in stations:
                line = _create_search_polyline(
                    (station[2], station[1]), radius)
                tasks.append(task_group.create_task(_fetch_for_location(
                    session, "USERDEFINEDAREA^{\"polylines\":\"" + line + "\"}", max_price, queue, station[0])))
            await asyncio.gather(*tasks)
            await queue.put(_POISON_PILL)
        await queue.join()
        print("Done!")
