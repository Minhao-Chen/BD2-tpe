"""q12 — Clientes sin ventas en el último año.

Propósito:
    Listar clientes sin ventas registradas en la ventana desde hace un año hasta hoy. Una venta
    de cualquier estado cuenta; una venta exactamente en el límite inferior cuenta como reciente.

Parámetros:
    hoy (date, opcional): día de referencia; por defecto es la fecha del sistema. La ventana no
    tiene límite superior en la consulta: fecha >= un_anio_atras(hoy).

Retorno:
    Datos planos del cliente y ultima_venta (date o None), ordenados por id_cliente.

Motor:
    MongoDB (aggregation). Desde clientes se hace `$lookup` de ventas con sub-pipeline que
    agrupa por `$max(fecha)`. Con la última venta alcanza para distinguir clientes sin ventas o
    con ultima_venta < cutoff; se usa el índice {id_cliente, fecha}. La relación es por
    referencia y se conserva también a clientes inactivos.

Uso:
    make consulta Q=q12
"""

import argparse
from datetime import date

from farmared.db import get_mongo_db
from farmared.fechas import a_datetime, resolver_hoy, un_anio_atras


def clientes_sin_ventas(hoy: date | None = None) -> list[dict]:
    hoy = resolver_hoy(hoy)
    cutoff = un_anio_atras(hoy)
    pipeline = [
        {"$lookup": {
            "from": "ventas",
            "localField": "_id",
            "foreignField": "id_cliente",
            "pipeline": [{"$group": {"_id": None, "ultima": {"$max": "$fecha"}}}],
            "as": "ventas",
        }},
        {"$set": {
            "ultima_venta": {"$arrayElemAt": ["$ventas.ultima", 0]},
        }},
        {"$match": {
            "$or": [
                {"ventas": {"$size": 0}},
                {"ultima_venta": {"$lt": a_datetime(cutoff)}},
            ],
        }},
        {"$project": {
            "_id": 0,
            "id_cliente": "$_id",
            "nombre": 1,
            "apellido": 1,
            "dni": 1,
            "email": "$contacto.email",
            "telefono": "$contacto.telefono",
            "ciudad": "$domicilio.ciudad",
            "provincia": "$domicilio.provincia",
            "obra_social": "$cobertura.obra_social",
            "nro_afiliado": "$cobertura.nro_afiliado",
            "activo": 1,
            "ultima_venta": 1,
        }},
        {"$sort": {"id_cliente": 1}},
    ]
    resultado = list(get_mongo_db().clientes.aggregate(pipeline))
    for cliente in resultado:
        if cliente.get("ultima_venta") is not None:
            cliente["ultima_venta"] = cliente["ultima_venta"].date()
        else:
            cliente["ultima_venta"] = None
    return resultado


def cli(argv: list[str]) -> list[dict]:
    argparse.ArgumentParser(
        prog="q12", description="Clientes sin ventas en el último año."
    ).parse_args(argv)
    return clientes_sin_ventas()
