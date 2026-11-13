"""Configuración leída de variables de entorno (y de `.env` si existe)."""

import os

from dotenv import load_dotenv

load_dotenv()

MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://mongo:27017/?replicaSet=rs0")
MONGO_DB: str = os.getenv("MONGO_DB", "farmared")
REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
