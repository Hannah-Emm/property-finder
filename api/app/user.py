from pydantic import BaseModel
from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
import jwt
from jwt.exceptions import InvalidTokenError
from .db import DBConnection, db_fetch_one
from datetime import datetime, timedelta
from os import getenv

_password_hash = PasswordHash.recommended()
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

_SECRET_KEY = getenv("SECRET_KEY")
_ALGORITHM = "HS256"
_DUMMY_HASH = _password_hash.hash("dummy")


class User(BaseModel):
    username: str


class Token(BaseModel):
    access_token: str
    token_type: str


async def get_current_user(db_connection: DBConnection, token: Annotated[str, Depends(_oauth2_scheme)]) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
        sub = payload.get("sub")
        if not sub or not sub.startswith("user."):
            raise credentials_exception
        username = sub.removeprefix("user.")
    except InvalidTokenError:
        raise credentials_exception
    db_user = await db_fetch_one(db_connection, "select username from users where username=%s", [username])
    if not db_user:
        raise credentials_exception
    return User(username=db_user[0])


def verify_password(plain: str, hashed: str) -> bool:
    return _password_hash.verify(plain, hashed)


def get_password_hash(password) -> str:
    return _password_hash.hash(password)


async def authenticate_user(db_connection: DBConnection, username: str, password: str) -> User | None:
    db_user = await db_fetch_one(db_connection, "select username, password from users where username=%s", [username])
    if not db_user:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, db_user[1]):
        return None
    return User(username=db_user[0])


def create_access_token(username: str, expiry_minutes: int = 1440) -> Token:
    content = {
        "sub": f"user.{username}",
        "exp": datetime.now() + timedelta(minutes=expiry_minutes)
    }
    return Token(access_token=jwt.encode(content, _SECRET_KEY, algorithm=_ALGORITHM), token_type="bearer")


type Current_User = Annotated[User, Depends(get_current_user)]
