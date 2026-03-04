from .db import db_execute_many, db_fetch_one, db_fetch_all
import aiohttp

_BASE_URL = "https://www.rightmove.co.uk/api/property-search/listing/search"
_PARAMS = {
    "locationIdentifier": "USERDEFINEDAREA^{\"polylines\":\"mdluHuovH~~c@|xeA?x|_D?dmwO?djwC?bbqD_waApknAyow@t{Zynh@rcA}fpC}re@ooqDijp@_|rBkso@?wehJ?sjfD?w|fG|oqAezcBj}b@gvpBr{z@uxpCtzwBbjTzkiFh|i@px`@hdP\"}",
    "channel": "RENT",
    "transactionType": "LETTING",
    "dontShow": "houseShare,retirement,student"
}
_HEADERS = {
    "Accept-Encoding": "gzip, deflate",
    "Accept": "application/json",
}


async def fetch_properties(db_pool) -> None:
    print("Fetching properties")
    index = 0
    next = None
    properties = []
    data = None
    async with aiohttp.ClientSession() as session:
        while (index != next):
            if next != None:
                index = next
            _PARAMS["index"] = index
            print(_PARAMS["index"])
            async with session.get(_BASE_URL, headers=_HEADERS, params=_PARAMS) as response:
                print(response.url)
                data = await response.json()
                if "pagination" in data and "next" in data["pagination"]:
                    next = int(data["pagination"]["next"])
                if "properties" in data:
                    properties += data['properties']
    print(data["pagination"])
    if properties:
        print(f"Found {len(properties)} properties")
        async with db_pool.connection() as connection:
            await store_properties(connection, properties)
    else:
        print("No properties found")


async def store_properties(connection, propertiesJson) -> None:
    if not propertiesJson:
        return
    properties = []
    ids = []
    for property in propertiesJson:
        id = property["id"]
        ids.append(id)
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

    print("Stored {} properties".format(len(properties)))

    old_properties_count = await db_fetch_one(connection, """
    with rows as (
        update properties set historic=true where historic=false and not (id = ANY(%s))
        returning OLD.id
    ) select count(1) from rows
    """, [ids])

    print(f"Marked {old_properties_count[0]} properties as historic")
