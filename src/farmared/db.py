"""Acceso a MongoDB y Redis. Cada conexión se crea una sola vez y se reutiliza."""

from functools import lru_cache

import redis
from pymongo import MongoClient
from pymongo.database import Database

from farmared import config


@lru_cache(maxsize=1)
def get_mongo_client() -> MongoClient:
    """Cliente de MongoDB compartido (pymongo maneja su propio pool)."""
    return MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000)


def get_mongo_db(name: str | None = None) -> Database:
    """Base de datos de la aplicación (por defecto `MONGO_DB`)."""
    return get_mongo_client()[name or config.MONGO_DB]


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    """Cliente de Redis compartido; devuelve strings en lugar de bytes."""
    return redis.Redis.from_url(config.REDIS_URL, decode_responses=True)
