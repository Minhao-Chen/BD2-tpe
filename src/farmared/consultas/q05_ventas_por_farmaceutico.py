"""q05 — Farmacéuticos activos y cantidad de ventas de los últimos 60 días.

Propósito:
    Para cada farmacéutico activo, contar las ventas que registró en los últimos 60 días,
    sin contar las anuladas. Los que no registraron ninguna aparecen con cantidad 0.

Parámetros:
    hoy (date, opcional): día contra el que se calcula la ventana. Por defecto es la fecha del
        sistema; solo se pasa en los tests. La ventana es  hoy - 60 días <= fecha <= hoy.

Retorno:
    Lista ordenada por cantidad de ventas (mayor a menor) y luego por id. Cada elemento:
    {id_farmaceutico, nombre, apellido, matricula, id_sucursal, cantidad_ventas}

Motor:
    MongoDB (aggregation). Se parte de `farmaceuticos` y no de `ventas`: así los que no tienen
    ventas no se pierden. La relación farmacéutico -> ventas se resuelve con un `$lookup` por
    referencia (`ventas.id_farmaceutico`) con sub-pipeline que filtra fecha y estado; usa el
    índice {id_farmaceutico, fecha}. Las ventas 'Pendiente' se cuentan: el enunciado solo
    excluye las anuladas.

Uso:
    make consulta Q=q05
"""

import argparse
from datetime import date

from farmared.db import get_mongo_db
from farmared.fechas import a_datetime, hace_dias, resolver_hoy

DIAS_VENTANA = 60


def ventas_por_farmaceutico(hoy: date | None = None) -> list[dict]:
    hoy = resolver_hoy(hoy)
    desde = hace_dias(hoy, DIAS_VENTANA)
    pipeline = [
        {"$match": {"activo": True}},
        {"$lookup": {
            "from": "ventas",
            "localField": "_id",
            "foreignField": "id_farmaceutico",
            "pipeline": [
                {"$match": {
                    "fecha": {"$gte": a_datetime(desde), "$lte": a_datetime(hoy)},
                    "estado": {"$ne": "Anulada"},
                }},
                {"$project": {"_id": 1}},
            ],
            "as": "ventas",
        }},
        {"$project": {
            "_id": 0,
            "id_farmaceutico": "$_id",
            "nombre": 1,
            "apellido": 1,
            "matricula": 1,
            "id_sucursal": 1,
            "cantidad_ventas": {"$size": "$ventas"},
        }},
        {"$sort": {"cantidad_ventas": -1, "id_farmaceutico": 1}},
    ]
    return list(get_mongo_db().farmaceuticos.aggregate(pipeline))


def cli(argv: list[str]) -> list[dict]:
    argparse.ArgumentParser(
        prog="q05", description="Ventas de los últimos 60 días por farmacéutico activo."
    ).parse_args(argv)
    return ventas_por_farmaceutico()
