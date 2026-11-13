"""q09 — Ventas libres de importe menor a 5.000.

Propósito:
    Listar ventas de tipo Venta libre con total estrictamente menor a 5.000, excluyendo las
    anuladas.

Parámetros:
    Ninguno.

Retorno:
    Lista ordenada por id_venta con los datos de la venta y fecha como date.

Motor:
    MongoDB (`find`). Se filtran tipo, total y estado; el índice {estado, fecha} no reemplaza
    el filtro por tipo, pero evita considerar ventas anuladas en el resultado.

Uso:
    make consulta Q=q09
"""

import argparse

from farmared.db import get_mongo_db


def ventas_libres_bajas() -> list[dict]:
    cursor = get_mongo_db().ventas.find(
        {"tipo": "Venta libre", "total": {"$lt": 5000}, "estado": {"$ne": "Anulada"}},
        {
            "_id": 1,
            "fecha": 1,
            "id_cliente": 1,
            "id_farmaceutico": 1,
            "id_sucursal": 1,
            "total": 1,
            "medio_pago": 1,
            "estado": 1,
        },
    ).sort("_id", 1)
    resultado = []
    for venta in cursor:
        venta["id_venta"] = venta.pop("_id")
        venta["fecha"] = venta["fecha"].date()
        resultado.append(venta)
    return resultado


def cli(argv: list[str]) -> list[dict]:
    argparse.ArgumentParser(
        prog="q09", description="Ventas libres de importe menor a 5.000."
    ).parse_args(argv)
    return ventas_libres_bajas()
