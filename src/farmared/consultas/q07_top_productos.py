"""q07 — Top 5 de productos más vendidos.

Propósito:
    Obtener los cinco productos con más unidades vendidas en ventas Completadas.

Parámetros:
    Ninguno.

Retorno:
    Lista ordenada por unidades descendentes e id_producto ascendente. Cada elemento contiene
    id_producto, nombre y unidades como entero. Si hay empate en el límite, se conserva el id
    menor entre todos los empatados.

Motor:
    Redis. `vistas.K_RANKING` contiene las unidades derivadas de MongoDB. Se lee el quinto
    puntaje y todos los productos empatados con él mediante `zrangebyscore`, se consultan sus
    nombres con un pipeline no transaccional y se ordena el resultado en Python. Antes se llama
    a `vistas.asegurar()`.

Uso:
    make consulta Q=q07
"""

import argparse

from farmared import vistas
from farmared.db import get_redis


def top_productos() -> list[dict]:
    vistas.asegurar()
    r = get_redis()
    primeros = r.zrevrange(vistas.K_RANKING, 0, 4, withscores=True)
    if not primeros:
        return []
    limite = primeros[-1][1]
    candidatos = r.zrangebyscore(vistas.K_RANKING, limite, "+inf", withscores=True)
    candidatos.sort(key=lambda item: (-item[1], item[0]))
    candidatos = candidatos[:5]
    pipe = r.pipeline(transaction=False)
    for id_producto, _ in candidatos:
        pipe.hget(vistas.k_producto(id_producto), "nombre")
    nombres = pipe.execute()
    return [
        {"id_producto": id_producto, "nombre": nombre, "unidades": int(unidades)}
        for (id_producto, unidades), nombre in zip(candidatos, nombres)
    ]


def cli(argv: list[str]) -> list[dict]:
    argparse.ArgumentParser(
        prog="q07", description="Top 5 de productos más vendidos."
    ).parse_args(argv)
    return top_productos()
