from enum import Enum
from .db import DBConnection, db_execute
from .user import CurrentUser


class PropertyPreference(str, Enum):
    STAR = "STAR"
    HIDE = "HIDE"


async def set_property_preference(db_connection: DBConnection, user: CurrentUser, property_id: int, preference: PropertyPreference):
    await db_execute(db_connection, """
                     insert into property_preferences (property_id, user_id, preference) values (%s, %s, %s)
                     on conflict (property_id, user_id)
                     do update set preference=excluded.preference""", [property_id, user.username, preference])


async def remove_property_preference(db_connection: DBConnection, user: CurrentUser, property_id: int):
    await db_execute(db_connection, "delete from property_preferences where property_id=%s and user_id=%s", [property_id, user.username])
