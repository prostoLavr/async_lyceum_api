from fastapi import Header, HTTPException
from os import environ
from redis import Redis
from uuid import uuid4
from enum import IntEnum

import logging

from sqlalchemy import select, exc

from .base import BaseService
from time_api import schemas
from time_api.db import tables


logger = logging.getLogger(__name__)


class AccessLevel(IntEnum):
    admin = 3
    teacher = 2
    monitor = 1
    unauthorized = 0


class UserService(BaseService):
    async def create(
            self,
            user_schema: schemas.auth.User
    ):
        new_user = tables.User(**user_schema.dict())
        try:
            self.session.add(new_user)
            await self.session.commit()
        except exc.IntegrityError:
            raise HTTPException(status_code=409)
        return new_user

    async def get(self, name: str):
        query = select(tables.User)
        query = query.filter_by(name=name)

        user = await self.session.scalar(query)
        if user is None:
            raise HTTPException(status_code=404)
        return user


class TokenAuth:
    EXPIRE_TIME = 3 * 24 * 60 * 60
    def __init__(self, *args, **kwargs):
        self.token = environ.get('AUTH_TOKEN', '123456')
        self.connection = Redis(*args, **kwargs)
        self.connection.hset(self.token,
                mapping={"name": "admin", "password": "", "access_level": AccessLevel.admin})
        self.connection.hset("teacher",
                mapping={"name": "teacher", "password": "", "access_level": AccessLevel.teacher})
        self.connection.hset("monitor",
                mapping={"name": "monitor", "password": "", "access_level": AccessLevel.monitor})

    def create_token(self, name: str, password: str, 
                    access_level: int = AccessLevel.unauthorized):
        if access_level not in AccessLevel:
            raise ValueError("invalid access_level")
        token_key = str(uuid4())
        with self.connection.pipeline() as pipeline:
            pipeline = pipeline.hset(token_key, 
                    mapping={"name": name, "password": password, "access_level": access_level})
            pipeline = pipeline.expire(token_key, self.EXPIRE_TIME)
            res = pipeline.execute()
        return token_key

    def refresh_token(self, token_key: str) -> str:
        return self.create_token(**self.connection.hgetall(token_key))

    def token_exists(self, token_key: str) -> bool:
        return self.connection.exists(token_key)

    def __call__(self, access_level=AccessLevel.unauthorized):
        token = self.token
        connection = self.connection

        def _auth(auth_token: str = Header(default='')) -> dict:
            if not self.token_exists(auth_token):
                raise HTTPException(status_code=401)
            user_access_level = connection.hget(auth_token, 'access_level')
            if int(user_access_level) < access_level:
                raise HTTPException(status_code=401)
            return dict(
                    [((k, v) if not v.isdigit() else (k, int(v)))
                        for k, v in connection.hgetall(auth_token).items()
                    ]
            )

        return _auth

    def admin(self):
        return self(AccessLevel.admin)

    def teacher(self):
        return self(AccessLevel.teacher)

    def monitor(self):
        return self(AccessLevel.monitor)


authenticate = TokenAuth(host='redis', charset="utf-8", decode_responses=True)
