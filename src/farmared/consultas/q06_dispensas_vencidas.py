"""q06 — Recetas de tratamiento prolongado con dispensa vencida.

Propósito:
    Listar recetas Vigentes de tratamiento prolongado cuya próxima dispensa es anterior a hoy.

Parámetros:
    hoy (date, opcional): fecha de referencia; por defecto es la fecha del sistema.

Retorno:
    Lista ordenada por proxima_dispensa e id_receta, con los datos de la receta y del cliente
    en forma plana.

Motor:
    MongoDB (aggregation). Se usa el índice {tipo, estado, proxima_dispensa} para filtrar
    estrictamente proxima_dispensa < hoy y `$lookup` para resolver receta -> cliente.

Uso:
    make consulta Q=q06
"""

import argparse
from datetime import date

from farmared.db import get_mongo_db
from farmared.fechas import a_datetime, resolver_hoy


def dispensas_vencidas(hoy: date | None = None) -> list[dict]:
    hoy = resolver_hoy(hoy)
    pipeline = [
        {"$match": {
            "tipo": "Tratamiento prolongado",
            "estado": "Vigente",
            "proxima_dispensa": {"$lt": a_datetime(hoy)},
        }},
        {"$lookup": {
            "from": "clientes",
            "localField": "id_cliente",
            "foreignField": "_id",
            "as": "cliente",
        }},
        {"$unwind": "$cliente"},
        {"$project": {
            "_id": 0,
            "id_receta": "$_id",
            "fecha_emision": 1,
            "medico": "$medico.nombre",
            "matricula_medico": "$medico.matricula",
            "dispensas_autorizadas": 1,
            "dispensas_realizadas": 1,
            "proxima_dispensa": 1,
            "estado": 1,
            "id_cliente": "$cliente._id",
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
        }},
        {"$sort": {"proxima_dispensa": 1, "id_receta": 1}},
    ]
    resultado = list(get_mongo_db().recetas.aggregate(pipeline))
    for receta in resultado:
        receta["fecha_emision"] = receta["fecha_emision"].date()
        receta["proxima_dispensa"] = receta["proxima_dispensa"].date()
    return resultado


def cli(argv: list[str]) -> list[dict]:
    argparse.ArgumentParser(
        prog="q06", description="Recetas con próxima dispensa vencida."
    ).parse_args(argv)
    return dispensas_vencidas()
