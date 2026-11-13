"""q01 — Productos activos con todos los datos de su proveedor.

Propósito:
    Listar el catálogo vigente (productos con activo = True) junto con los datos completos del
    proveedor habitual de cada uno.

Parámetros:
    Ninguno.

Retorno:
    Lista de productos ordenada por id. Cada elemento:
    {id_producto, nombre, principio_activo, categoria, presentacion, condicion_venta,
     precio_unit, activo,
     proveedor: {id_proveedor, razon_social, cuit, tipo, ciudad, provincia, telefono, activo}}

Motor:
    Redis. El catálogo cambia poco y se lee mucho, así que se sirve desde el modelo de lectura:
    un SET con los ids activos y un HASH por producto que ya trae los datos del proveedor
    (la relación producto -> proveedor se resuelve al construir la vista, no al leer).
    La fuente de verdad es MongoDB (`productos` y `proveedores`): si las vistas no existen,
    `vistas.asegurar()` las reconstruye desde ahí antes de responder.

Uso:
    make consulta Q=q01
"""

import argparse

from farmared import vistas
from farmared.db import get_redis


def productos_activos_con_proveedor() -> list[dict]:
    vistas.asegurar()
    r = get_redis()
    ids = sorted(r.smembers(vistas.K_ACTIVOS))
    pipe = r.pipeline(transaction=False)
    for id_producto in ids:
        pipe.hgetall(vistas.k_producto(id_producto))
    return [vistas.hash_a_producto(campos) for campos in pipe.execute()]


def cli(argv: list[str]) -> list[dict]:
    argparse.ArgumentParser(prog="q01", description="Productos activos con su proveedor.").parse_args(argv)
    return productos_activos_con_proveedor()
