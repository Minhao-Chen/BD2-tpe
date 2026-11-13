"""q02 — Ventas pendientes con farmacéutico y sucursal.

Propósito:
    Listar las ventas en estado Pendiente junto con el farmacéutico asignado y su sucursal.

Parámetros:
    Ninguno.

Retorno:
    Lista ordenada por id_venta. Cada elemento contiene id_venta, fecha, total, nombre,
    apellido, matricula y sucursal (id_sucursal, nombre).

Motor:
    MongoDB (aggregation). Se encadenan referencias mediante `$lookup`: venta ->
    farmacéutico -> sucursal. Se consulta la sucursal actual del farmacéutico; el farmacéutico
    aparece aunque esté inactivo. Al cargar, D06 copia esa sucursal en la venta y los datos
    originales son coherentes, pero aquí se sigue la relación actual.

Uso:
    make consulta Q=q02
"""

import argparse

from farmared.db import get_mongo_db


def ventas_pendientes() -> list[dict]:
    pipeline = [
        {"$match": {"estado": "Pendiente"}},
        {"$lookup": {
            "from": "farmaceuticos",
            "localField": "id_farmaceutico",
            "foreignField": "_id",
            "as": "farmaceutico",
        }},
        {"$unwind": "$farmaceutico"},
        {"$lookup": {
            "from": "sucursales",
            "localField": "farmaceutico.id_sucursal",
            "foreignField": "_id",
            "as": "sucursal",
        }},
        {"$unwind": "$sucursal"},
        {"$project": {
            "_id": 0,
            "id_venta": "$_id",
            "fecha": 1,
            "total": 1,
            "nombre": "$farmaceutico.nombre",
            "apellido": "$farmaceutico.apellido",
            "matricula": "$farmaceutico.matricula",
            "sucursal": {
                "id_sucursal": "$sucursal._id",
                "nombre": "$sucursal.nombre",
            },
        }},
        {"$sort": {"id_venta": 1}},
    ]
    resultado = list(get_mongo_db().ventas.aggregate(pipeline))
    for venta in resultado:
        venta["fecha"] = venta["fecha"].date()
    return resultado


def cli(argv: list[str]) -> list[dict]:
    argparse.ArgumentParser(
        prog="q02", description="Ventas pendientes con farmacéutico y sucursal."
    ).parse_args(argv)
    return ventas_pendientes()
