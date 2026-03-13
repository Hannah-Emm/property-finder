from .db import DBConnection, db_execute, db_fetch_all
from .user import CurrentUser
from .property import Property
from .enums import PropertyPreference

_PROPERTY_WITH_PREFERENCE_QUERY_TEMPLATE = """
    select id, ST_X(location::geometry), ST_Y(location::geometry), address, price, bedrooms, bathrooms, pref.preference = 'STAR'
    from properties as prop join property_preferences pref
    on pref.property_id=prop.id and pref.user_id=%s
    where pref.preference=%s
    """


async def set_property_preference(db_connection: DBConnection, user: CurrentUser, property_id: int, preference: PropertyPreference) -> None:
    await db_execute(db_connection, """
                     insert into property_preferences (property_id, user_id, preference) values (%s, %s, %s)
                     on conflict (property_id, user_id)
                     do update set preference=excluded.preference""", [property_id, user.username, preference])


async def remove_property_preference(db_connection: DBConnection, user: CurrentUser, property_id: int) -> None:
    await db_execute(db_connection, "delete from property_preferences where property_id=%s and user_id=%s", [property_id, user.username])


async def _get_property_with_preference(db_connection: DBConnection, user: CurrentUser, preference: PropertyPreference):
    rows = await db_fetch_all(db_connection, _PROPERTY_WITH_PREFERENCE_QUERY_TEMPLATE, [user.username, preference])
    properties = []
    for row in rows:
        properties.append(Property(id=str(row[0]), location=(
            row[1], row[2]), address=row[3], price=row[4], bedrooms=row[5], bathrooms=row[6], star=row[7]))
    return properties


async def get_stared_properties(db_connection: DBConnection, user: CurrentUser) -> list[Property]:
    return await _get_property_with_preference(db_connection, user, PropertyPreference.STAR)


async def get_hidden_properties(db_connection: DBConnection, user: CurrentUser) -> list[Property]:
    return await _get_property_with_preference(db_connection, user, PropertyPreference.HIDE)
