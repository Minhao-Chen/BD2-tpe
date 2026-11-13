"""Tests de q01 (Redis) y q05 (MongoDB), y de las vistas de Redis."""

from datetime import date

from conftest import HOY

from farmared import vistas
from farmared.consultas.q01_productos_proveedor import productos_activos_con_proveedor
from farmared.consultas.q05_ventas_por_farmaceutico import ventas_por_farmaceutico
from farmared.db import get_redis


def test_q01_productos_activos_con_proveedor(base):
    resultado = productos_activos_con_proveedor()

    # PRD012 y PRD013 están discontinuados.
    assert [p["id_producto"] for p in resultado] == [f"PRD{n:03d}" for n in range(1, 12)]
    prd004 = next(p for p in resultado if p["id_producto"] == "PRD004")
    assert prd004["precio_unit"] == 6200
    assert prd004["activo"] is True
    assert prd004["proveedor"] == {
        "id_proveedor": "PRV002",
        "razon_social": "DroguMed S.R.L.",
        "cuit": "30-70987654-3",
        "tipo": "Droguería",
        "ciudad": "Córdoba",
        "provincia": "Córdoba",
        "telefono": "3514102200",
        "activo": True,
    }


def test_q01_coincide_con_mongo(base):
    desde_mongo = {
        p["_id"]: p["proveedor"][0]["razon_social"]
        for p in base.productos.aggregate([
            {"$match": {"activo": True}},
            {"$lookup": {"from": "proveedores", "localField": "id_proveedor",
                         "foreignField": "_id", "as": "proveedor"}},
        ])
    }
    desde_redis = {
        p["id_producto"]: p["proveedor"]["razon_social"]
        for p in productos_activos_con_proveedor()
    }
    assert desde_redis == desde_mongo


def test_vistas_se_reconstruyen_solas_si_redis_esta_vacio(base):
    r = get_redis()
    r.flushdb()  # db 15, solo de tests
    assert len(productos_activos_con_proveedor()) == 11
    assert r.exists(vistas.K_OK)


def test_vistas_de_ranking_e_ingresos(base):
    r = get_redis()
    top = r.zrevrange(vistas.K_RANKING, 0, 4, withscores=True)
    assert top == [("PRD005", 6.0), ("PRD011", 5.0), ("PRD001", 4.0), ("PRD004", 3.0), ("PRD009", 2.0)]
    # Octubre 2026, solo Completadas: V010 (F003), V013 (F001), V014 (F005), V016 (F002).
    assert dict(r.zrange(vistas.k_ingresos("2026-10"), 0, -1, withscores=True)) == {
        "F001": 4400.0, "F002": 7800.0, "F003": 7100.0, "F005": 4600.0,
    }


def test_q05_ventas_ultimos_60_dias(base):
    resultado = ventas_por_farmaceutico(hoy=HOY)  # ventana: 14/08 al 13/10

    cantidades = {f["id_farmaceutico"]: f["cantidad_ventas"] for f in resultado}
    # F004 está inactivo y no aparece; F007 no tiene ventas y aparece con 0.
    # La anulada V015 (F002) no se cuenta; las pendientes V011 y V012 sí.
    assert cantidades == {"F001": 2, "F002": 3, "F003": 1, "F005": 3, "F006": 2, "F007": 0}
    assert [f["id_farmaceutico"] for f in resultado] == ["F002", "F005", "F001", "F006", "F003", "F007"]
    assert resultado[0] == {
        "id_farmaceutico": "F002", "nombre": "Sebastián", "apellido": "Ledesma",
        "matricula": "MN-18078", "id_sucursal": "S001", "cantidad_ventas": 3,
    }


def test_q05_la_ventana_se_mueve_con_la_fecha(base):
    # Un mes después (ventana: 14/09 al 13/11) quedan afuera V003, V005 y V007.
    cantidades = {
        f["id_farmaceutico"]: f["cantidad_ventas"]
        for f in ventas_por_farmaceutico(hoy=date(2026, 11, 13))
    }
    assert cantidades == {"F001": 1, "F002": 2, "F003": 1, "F005": 3, "F006": 1, "F007": 0}
