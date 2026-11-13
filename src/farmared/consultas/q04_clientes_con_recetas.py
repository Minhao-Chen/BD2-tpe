"""q04 — Clientes con más de una receta.

Propósito:
    Contar las recetas de cada cliente y devolver quienes tienen más de una, sin importar su
    estado.

Parámetros:
    Ninguno.

Retorno:
    Lista con los datos planos del cliente y cantidad_recetas, ordenada por cantidad descendente
    e id_cliente ascendente.

Motor:
    MongoDB (aggregation). Se agrupa recetas por id_cliente y luego se resuelve la referencia
    con `$lookup` a clientes. El índice {id_cliente} de recetas permite el acceso por cliente.

Uso:
    make consulta Q=q04
"""

import argparse

from farmared.db import get_mongo_db


def clientes_con_recetas() -> list[dict]:
    pipeline = [
        {"$group": {"_id": "$id_cliente", "cantidad_recetas": {"$sum": 1}}},
        {"$match": {"cantidad_recetas": {"$gt": 1}}},
        {"$lookup": {
            "from": "clientes",
            "localField": "_id",
            "foreignField": "_id",
            "as": "cliente",
        }},
        {"$unwind": "$cliente"},
        {"$project": {
            "_id": 0,
            "id_cliente": "$_id",
            "nombre": "$cliente.nombre",
            "apellido": "$cliente.apellido",
            "dni": "$cliente.dni",
            "email": "$cliente.contacto.email",
            "telefono": "$cliente.contacto.telefono",
            "ciudad": "$cliente.domicilio.ciudad",
            "provincia": "$cliente.domicilio.provincia",
            "obra_social": "$cliente.cobertura.obra_social",
            "nro_afiliado": "$cliente.cobertura.nro_afiliado",
            "activo": "$cliente.activo",
            "cantidad_recetas": 1,
        }},
        {"$sort": {"cantidad_recetas": -1, "id_cliente": 1}},
    ]
    return list(get_mongo_db().recetas.aggregate(pipeline))


def cli(argv: list[str]) -> list[dict]:
    argparse.ArgumentParser(
        prog="q04", description="Clientes con más de una receta."
    ).parse_args(argv)
    return clientes_con_recetas()
