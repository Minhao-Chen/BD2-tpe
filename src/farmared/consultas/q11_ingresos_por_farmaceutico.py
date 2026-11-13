"""q11 — Ingresos por farmacéutico del mes actual.

Propósito:
    Listar los ingresos de ventas Completadas por farmacéutico en el mes actual.

Parámetros:
    hoy (date, opcional): día de referencia; por defecto es la fecha del sistema.

Retorno:
    Solo farmacéuticos con ingresos, ordenados por ingresos descendentes e id_farmaceutico.
    Incluye id_farmaceutico, nombre, apellido, matricula, id_sucursal, activo e ingresos.

Motor:
    Redis aporta el ZSET mensual y sus puntajes ordenados. Se llama `vistas.asegurar()` antes
    de leerlo. Luego se resuelven todos los farmacéuticos con una sola consulta MongoDB `$in`;
    los ids faltantes se conservan con datos None. La vista solo incluye ventas Completadas.

Uso:
    make consulta Q=q11
"""

import argparse
from datetime import date

from farmared import vistas
from farmared.db import get_mongo_db, get_redis
from farmared.fechas import clave_mes, resolver_hoy


def ingresos_por_farmaceutico(hoy: date | None = None) -> list[dict]:
    hoy = resolver_hoy(hoy)
    vistas.asegurar()
    filas = get_redis().zrevrange(vistas.k_ingresos(clave_mes(hoy)), 0, -1, withscores=True)
    if not filas:
        return []

    ids = [id_farmaceutico for id_farmaceutico, _ in filas]
    farmaceuticos = {
        farmaceutico["_id"]: farmaceutico
        for farmaceutico in get_mongo_db().farmaceuticos.find({"_id": {"$in": ids}})
    }
    resultado = []
    for id_farmaceutico, ingresos in filas:
        farmaceutico = farmaceuticos.get(id_farmaceutico)
        resultado.append({
            "id_farmaceutico": id_farmaceutico,
            "nombre": farmaceutico["nombre"] if farmaceutico else None,
            "apellido": farmaceutico["apellido"] if farmaceutico else None,
            "matricula": farmaceutico["matricula"] if farmaceutico else None,
            "id_sucursal": farmaceutico["id_sucursal"] if farmaceutico else None,
            "activo": farmaceutico["activo"] if farmaceutico else None,
            "ingresos": int(ingresos),
        })
    resultado.sort(key=lambda fila: (-fila["ingresos"], fila["id_farmaceutico"]))
    return resultado


def cli(argv: list[str]) -> list[dict]:
    argparse.ArgumentParser(
        prog="q11", description="Ingresos por farmacéutico del mes actual."
    ).parse_args(argv)
    return ingresos_por_farmaceutico()
