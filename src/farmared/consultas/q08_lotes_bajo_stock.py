"""q08 — Lotes con menos de 50 unidades.

Propósito:
    Listar lotes con unidades estrictamente menores que 50, incluso si están vacíos o vencidos.

Parámetros:
    hoy (date, opcional): fecha de referencia para marcar vencido; por defecto es la del sistema.

Retorno:
    Lista ordenada por unidades e id_lote. Incluye lote, producto, proveedor y sucursal, además
    de vencido: vencimiento < hoy. Se conservan productos y proveedores inactivos.

Motor:
    MongoDB (aggregation). Se filtra con el índice {unidades} y se resuelven las referencias
    lote -> producto -> proveedor y lote -> sucursal mediante `$lookup`.

Uso:
    make consulta Q=q08
"""

import argparse
from datetime import date

from farmared.db import get_mongo_db
from farmared.fechas import a_datetime, resolver_hoy


def lotes_bajo_stock(hoy: date | None = None) -> list[dict]:
    hoy = resolver_hoy(hoy)
    pipeline = [
        {"$match": {"unidades": {"$lt": 50}}},
        {"$lookup": {
            "from": "productos",
            "localField": "id_producto",
            "foreignField": "_id",
            "as": "producto",
        }},
        {"$unwind": "$producto"},
        {"$lookup": {
            "from": "proveedores",
            "localField": "producto.id_proveedor",
            "foreignField": "_id",
            "as": "proveedor",
        }},
        {"$unwind": "$proveedor"},
        {"$lookup": {
            "from": "sucursales",
            "localField": "id_sucursal",
            "foreignField": "_id",
            "as": "sucursal",
        }},
        {"$unwind": "$sucursal"},
        {"$project": {
            "_id": 0,
            "id_lote": "$_id",
            "nro_lote": 1,
            "unidades": 1,
            "vencimiento": 1,
            "vencido": {"$lt": ["$vencimiento", a_datetime(hoy)]},
            "producto": {
                "id_producto": "$producto._id",
                "nombre": "$producto.nombre",
                "activo": "$producto.activo",
            },
            "proveedor": {
                "id_proveedor": "$proveedor._id",
                "razon_social": "$proveedor.razon_social",
                "activo": "$proveedor.activo",
            },
            "sucursal": {
                "id_sucursal": "$sucursal._id",
                "nombre": "$sucursal.nombre",
                "tipo": "$sucursal.tipo",
            },
        }},
        {"$sort": {"unidades": 1, "id_lote": 1}},
    ]
    resultado = list(get_mongo_db().stock_lotes.aggregate(pipeline))
    for lote in resultado:
        lote["vencimiento"] = lote["vencimiento"].date()
    return resultado


def cli(argv: list[str]) -> list[dict]:
    argparse.ArgumentParser(
        prog="q08", description="Lotes con menos de 50 unidades."
    ).parse_args(argv)
    return lotes_bajo_stock()
