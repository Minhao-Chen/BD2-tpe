"""Configuración leída de variables de entorno (y de `.env` si existe)."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

RAIZ: Path = Path(__file__).resolve().parents[2]

MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://mongo:27017/?replicaSet=rs0")
MONGO_DB: str = os.getenv("MONGO_DB", "farmared")
REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Zona horaria del negocio: define qué día es "hoy" para consultas y servicios.
ZONA_HORARIA: str = os.getenv("FARMARED_TZ", "America/Argentina/Buenos_Aires")

DIR_ORIGINALES: Path = RAIZ / "data" / "original"
DIR_ADICIONALES: Path = RAIZ / "data" / "extra"
