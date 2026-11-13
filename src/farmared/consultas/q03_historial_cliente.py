"""q03 — Historial completo de un cliente.

Propósito:
    Unir las ventas y recetas de un cliente en un historial cronológico.

Parámetros:
    id_cliente (str): cliente cuyo historial se consulta.

Retorno:
    Lista ordenada por fecha ascendente, tipo_registro (receta antes que venta en empate) e
    id_registro. Los campos específicos de ventas o recetas que no aplican valen None.

Motor:
    MongoDB (aggregation). Se consulta la existencia del cliente y se combinan las dos
    colecciones con `$unionWith`, proyectando ambas ramas a la misma forma. `recetas.id_cliente`
    usa el índice {id_cliente}; la rama de ventas usa {id_cliente, fecha}.

Uso:
    make consulta Q=q03 ARGS="C001"
"""

import argparse

from farmared.db import get_mongo_db
from farmared.errores import ErrorValidacion


def historial_cliente(id_cliente: str) -> list[dict]:
    db = get_mongo_db()
    if db.clientes.find_one({"_id": id_cliente}, {"_id": 1}) is None:
        raise ErrorValidacion(f"el cliente {id_cliente} no existe")

    pipeline = [
        {"$match": {"id_cliente": id_cliente}},
        {"$project": {
            "_id": 0,
            "fecha": 1,
            "tipo_registro": {"$literal": "venta"},
            "id_registro": "$_id",
            "tipo": 1,
            "estado": 1,
            "id_farmaceutico": 1,
            "id_sucursal": 1,
            "id_receta": 1,
            "medio_pago": 1,
            "total": 1,
            "medico": {"$literal": None},
            "dispensas_autorizadas": {"$literal": None},
            "dispensas_realizadas": {"$literal": None},
            "proxima_dispensa": {"$literal": None},
        }},
        {"$unionWith": {
            "coll": "recetas",
            "pipeline": [
                {"$match": {"id_cliente": id_cliente}},
                {"$project": {
                    "_id": 0,
                    "fecha": "$fecha_emision",
                    "tipo_registro": {"$literal": "receta"},
                    "id_registro": "$_id",
                    "tipo": 1,
                    "estado": 1,
                    "id_farmaceutico": {"$literal": None},
                    "id_sucursal": {"$literal": None},
                    "id_receta": {"$literal": None},
                    "medio_pago": {"$literal": None},
                    "total": {"$literal": None},
                    "medico": 1,
                    "dispensas_autorizadas": 1,
                    "dispensas_realizadas": 1,
                    "proxima_dispensa": 1,
                }},
            ],
        }},
        {"$sort": {"fecha": 1, "tipo_registro": 1, "id_registro": 1}},
    ]
    resultado = list(db.ventas.aggregate(pipeline))
    for registro in resultado:
        registro["fecha"] = registro["fecha"].date()
        if registro["proxima_dispensa"] is not None:
            registro["proxima_dispensa"] = registro["proxima_dispensa"].date()
    return resultado


def cli(argv: list[str]) -> list[dict]:
    parser = argparse.ArgumentParser(prog="q03", description="Historial completo de un cliente.")
    parser.add_argument("id_cliente")
    args = parser.parse_args(argv)
    return historial_cliente(args.id_cliente)
