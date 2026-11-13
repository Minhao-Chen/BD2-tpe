"""Configuración común de los tests.

Los tests corren contra MongoDB y Redis reales (los del docker-compose), pero aislados de los
datos de trabajo: usan la base `farmared_test` y la db 15 de Redis.

Fixtures:
- `base`: deja cargados SOLO los CSV originales, con HOY como fecha, y devuelve la base de
  Mongo. Se vuelve a cargar antes de cada test, así ninguno depende de otro.

Los valores esperados de los tests están calculados a mano sobre los CSV originales con
HOY = 13/10/2026, la fecha de referencia del enunciado.
"""

import os
import re
from datetime import date

import pytest
from dotenv import load_dotenv

# Debe ejecutarse antes de importar `farmared`: config lee el entorno al importarse.
load_dotenv()
os.environ["MONGO_DB"] = "farmared_test"
os.environ["REDIS_URL"] = (
    re.sub(r"/\d+$", "", os.environ.get("REDIS_URL", "redis://redis:6379/0")) + "/15"
)

from farmared.carga.cargador import cargar  # noqa: E402
from farmared.db import get_mongo_client, get_mongo_db, get_redis  # noqa: E402

HOY = date(2026, 10, 13)


@pytest.fixture(scope="session")
def entorno():
    """Falla una sola vez, y rápido, si Mongo o Redis no están disponibles."""
    get_mongo_client().admin.command("ping")
    get_redis().ping()


@pytest.fixture
def base(entorno, tmp_path):
    """Estado inicial con los datos originales (sin registros adicionales)."""
    cargar(hoy=HOY, dir_adicionales=tmp_path)
    return get_mongo_db()


def foto(db) -> dict:
    """Contenido completo de lo que un servicio de venta puede modificar."""
    return {
        coleccion: list(db[coleccion].find().sort("_id", 1))
        for coleccion in ("ventas", "recetas", "stock_lotes")
    }
