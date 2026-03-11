from .db import DBConnection, db_execute, db_fetch_all
from .user import CurrentUser
from .property import Property
from .enums import PropertyPreference


async def set_property_preference(db_connection: DBConnection, user: CurrentUser, property_id: int, preference: PropertyPreference) -> None:
    await db_execute(db_connection, """
                     insert into property_preferences (property_id, user_id, preference) values (%s, %s, %s)
                     on conflict (property_id, user_id)
                     do update set preference=excluded.preference""", [property_id, user.username, preference])


async def remove_property_preference(db_connection: DBConnection, user: CurrentUser, property_id: int) -> None:
    await db_execute(db_connection, "delete from property_preferences where property_id=%s and user_id=%s", [property_id, user.username])


async def get_stared_properties(db_connection: DBConnection, user: CurrentUser) -> list[Property]:
    rows = await db_fetch_all(db_connection, """
    select id, ST_X(location::geometry), ST_Y(location::geometry), address, price, bedrooms, bathrooms
    from properties as prop join property_preferences pref
    on pref.property_id=prop.id and pref.user_id=%s
    where pref.preference='STAR'
    """, [user.username])
    properties = []
    for row in rows:
        properties.append(Property(id=str(row[0]), location=(
            row[1], row[2]), address=row[3], price=row[4], bedrooms=row[5], bathrooms=row[6], star=True))
    return properties
