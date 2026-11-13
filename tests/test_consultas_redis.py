"""Pruebas de las consultas nuevas sobre Redis."""

from datetime import date

from conftest import HOY

from farmared import vistas
from farmared.consultas.q07_top_productos import top_productos
from farmared.consultas.q11_ingresos_por_farmaceutico import ingresos_por_farmaceutico
from farmared.db import get_redis


def test_q07_top_productos_y_desempate(base):
    assert [p["id_producto"] for p in top_productos()] == [
        "PRD005", "PRD011", "PRD001", "PRD004", "PRD009",
    ]
    assert all(isinstance(p["unidades"], int) for p in top_productos())


def test_q11_ingresos_del_mes(base):
    # Octubre: solo las Completadas V010, V013, V014 y V016.
    assert [(f["id_farmaceutico"], f["ingresos"]) for f in ingresos_por_farmaceutico(hoy=HOY)] == [
        ("F002", 7800), ("F003", 7100), ("F005", 4600), ("F001", 4400),
    ]
    assert ingresos_por_farmaceutico(hoy=date(2027, 1, 15)) == []


def test_q07_y_q11_reconstruyen_redis(base):
    r = get_redis()
    assert r.connection_pool.connection_kwargs.get("db") == 15
    r.flushdb()
    assert len(top_productos()) == 5
    assert len(ingresos_por_farmaceutico(hoy=HOY)) == 4
    assert r.exists(vistas.K_OK)
