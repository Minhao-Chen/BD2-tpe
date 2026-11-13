"""q10 — Clientes atendidos en una sucursal.

Propósito:
    Listar una vez cada cliente que tiene ventas registradas en una sucursal y contar sus ventas.

Parámetros:
    id_sucursal (str): sucursal consultada.

Retorno:
    Lista de clientes en forma plana con cantidad_ventas, ordenada por id_cliente. Se cuentan
    ventas de cualquier estado.

Motor:
    MongoDB (aggregation). Se valida la sucursal y se agrupan ventas por id_cliente usando
    ventas.id_sucursal (D06: fue copiado del farmacéutico al registrar la venta). Así el
    enunciado "a través del farmacéutico" queda resuelto por el hecho histórico de la sucursal,
    sin depender de que el farmacéutico siga activo. Después se hace `$lookup` a clientes.

Uso:
    make consulta Q=q10 ARGS="S001"
"""

import argparse

from farmared.db import get_mongo_db
from farmared.errores import ErrorValidacion


def clientes_por_sucursal(id_sucursal: str) -> list[dict]:
    db = get_mongo_db()
    if db.sucursales.find_one({"_id": id_sucursal}, {"_id": 1}) is None:
        raise ErrorValidacion(f"la sucursal {id_sucursal} no existe")
    pipeline = [
        {"$match": {"id_sucursal": id_sucursal}},
        {"$group": {"_id": "$id_cliente", "cantidad_ventas": {"$sum": 1}}},
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
            "cantidad_ventas": 1,
        }},
        {"$sort": {"id_cliente": 1}},
    ]
    return list(db.ventas.aggregate(pipeline))


def cli(argv: list[str]) -> list[dict]:
    parser = argparse.ArgumentParser(
        prog="q10", description="Clientes atendidos en una sucursal."
    )
    parser.add_argument("id_sucursal")
    args = parser.parse_args(argv)
    return clientes_por_sucursal(args.id_sucursal)
