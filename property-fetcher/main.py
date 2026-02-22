import requests
import json
from time import sleep
import psycopg

baseUrl = 'https://www.rightmove.co.uk/api/property-search/listing/search'
params = {
    'locationIdentifier': 'USERDEFINEDAREA^{"polylines":"mdluHuovH~~c@|xeA?x|_D?dmwO?djwC?bbqD_waApknAyow@t{Zynh@rcA}fpC}re@ooqDijp@_|rBkso@?wehJ?sjfD?w|fG|oqAezcBj}b@gvpBr{z@uxpCtzwBbjTzkiFh|i@px`@hdP"}',
    'channel': 'RENT',
    'sortType': '6',
    'transactionType': 'LETTING',
    'displayLocationIdentifier': 'undefined',
    'dontShow': 'houseShare,retirement,student',
    'maxPrice': '1400',
    'minBedrooms': '1'
}
headers = {}

def fetchProperties(cursor):
    index = 0
    next = None
    while (index != next):
        if next != None:
            index = next
        params['index'] = index
        r = requests.get(baseUrl, params=params, headers=headers)
        response = json.loads(r.text)
        if 'pagination' not in response:
            print('No pagination')
            print(response)
        elif 'next' not in response['pagination']:
            print('No next page')
        else:
            next = int(response['pagination']['next'])
        storeProperties(cursor, response['properties'])
        sleep(0.1)

def storeProperties(cursor, propertiesJson):
    if len(propertiesJson) == 0:
        return
    properties = []
    for property in propertiesJson:
        id = property['id']
        longitude = property['location']['longitude']
        latitude = property['location']['latitude']
        location = "point({} {})".format(longitude, latitude)
        address = property['displayAddress']
        #TODO: handle non monthly prices
        price = property['price']['amount']
        bedrooms = property['bedrooms']
        bathrooms = property['bathrooms']
        properties.append([id, location, address, price, bedrooms, bathrooms])

    cursor.executemany(
    """INSERT INTO properties (id, location, address, price, bedrooms, bathrooms) 
    values (%s, %s, %s, %s, %s, %s) 
    ON CONFLICT(id) DO UPDATE SET 
    location = EXCLUDED.location,
    address = EXCLUDED.address,
    price = EXCLUDED.price,
    bedrooms = EXCLUDED.bedrooms,
    bathrooms = EXCLUDED.bathrooms
    """, 
    properties)
    print("Stored {} properties".format(len(properties)))

if __name__ == "__main__":
    print('Started!')
    with psycopg.connect("dbname=db host=db user=admin password=admin") as connection:
        with connection.cursor() as cursor:
            fetchProperties(cursor)
            connection.commit()