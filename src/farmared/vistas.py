"""Modelo de lectura en Redis: datos derivados de MongoDB, listos para leer.

MongoDB es la fuente de verdad. Redis guarda tres vistas que se pueden rearmar en cualquier
momento a partir de Mongo (por eso Redis no necesita persistencia):

    farmared:producto:{id}        HASH  producto con los datos de su proveedor ya incluidos
    farmared:productos:activos    SET   ids de los productos activos                  (q01)
    farmared:ranking:productos    ZSET  id_producto -> unidades vendidas              (q07)
    farmared:ingresos:{AAAA-MM}   ZSET  id_farmaceutico -> ingresos del mes en ARS    (q11)
    farmared:vistas:ok            marca de que las vistas están construidas

Las dos últimas vistas cuentan solo ventas 'Completada'.

Mantenimiento:
- `reconstruir()` las rearma completas desde Mongo (lo hace la carga y `make reconstruir-vistas`).
- `asegurar()` las reconstruye si falta la marca: un Redis vacío o reiniciado se repara solo.
- `aplicar_venta()` suma una venta recién confirmada, sin recalcular todo.

Consistencia: la venta se confirma primero en Mongo y después se suma en Redis. Si ese segundo
paso falla, la venta queda bien registrada y las vistas quedan atrasadas hasta la próxima
reconstrucción (consistencia eventual).
"""

from farmared.db import get_mongo_db, get_redis
from farmared.fechas import clave_mes

PREFIJO = "farmared:"
K_OK = PREFIJO + "vistas:ok"
K_ACTIVOS = PREFIJO + "productos:activos"
K_RANKING = PREFIJO + "ranking:productos"

_CAMPOS_PRODUCTO = ("nombre", "principio_activo", "categoria", "presentacion", "condicion_venta")
_CAMPOS_PROVEEDOR = ("razon_social", "cuit", "tipo", "ciudad", "provincia", "telefono")


def k_producto(id_producto: str) -> str:
    return f"{PREFIJO}producto:{id_producto}"


def k_ingresos(mes: str) -> str:
    """Clave de ingresos de un mes 'AAAA-MM'."""
    return f"{PREFIJO}ingresos:{mes}"


def _producto_a_hash(producto: dict, proveedor: dict) -> dict[str, str]:
    """Aplana producto + proveedor en los campos de texto de un HASH."""
    campos = {"id_producto": producto["_id"], "id_proveedor": proveedor["_id"]}
    campos.update((c, producto[c]) for c in _CAMPOS_PRODUCTO)
    campos["precio_unit"] = str(producto["precio_unit"])
    campos["activo"] = "1" if producto["activo"] else "0"
    campos.update((f"proveedor_{c}", proveedor[c]) for c in _CAMPOS_PROVEEDOR)
    campos["proveedor_activo"] = "1" if proveedor["activo"] else "0"
    return campos


def hash_a_producto(campos: dict[str, str]) -> dict:
    """Inversa de `_producto_a_hash`: producto con el proveedor anidado y tipos correctos."""
    producto = {"id_producto": campos["id_producto"]}
    producto.update((c, campos[c]) for c in _CAMPOS_PRODUCTO)
    producto["precio_unit"] = int(campos["precio_unit"])
    producto["activo"] = campos["activo"] == "1"
    proveedor = {"id_proveedor": campos["id_proveedor"]}
    proveedor.update((c, campos[f"proveedor_{c}"]) for c in _CAMPOS_PROVEEDOR)
    proveedor["activo"] = campos["proveedor_activo"] == "1"
    producto["proveedor"] = proveedor
    return producto


def reconstruir() -> dict[str, int]:
    """Rearma todas las vistas desde MongoDB, en un único MULTI/EXEC.

    Retorna la cantidad de elementos de cada vista.
    """
    db = get_mongo_db()
    r = get_redis()

    proveedores = {p["_id"]: p for p in db.proveedores.find()}
    productos = list(db.productos.find())
    unidades = {
        d["_id"]: d["unidades"]
        for d in db.ventas.aggregate([
            {"$match": {"estado": "Completada"}},
            {"$unwind": "$items"},
            {"$group": {"_id": "$items.id_producto", "unidades": {"$sum": "$items.cantidad"}}},
        ])
    }
    ingresos = list(db.ventas.aggregate([
        {"$match": {"estado": "Completada"}},
        {"$group": {
            "_id": {
                "mes": {"$dateToString": {"format": "%Y-%m", "date": "$fecha"}},
                "id_farmaceutico": "$id_farmaceutico",
            },
            "total": {"$sum": "$total"},
        }},
    ]))

    anteriores = list(r.scan_iter(match=PREFIJO + "*"))
    pipe = r.pipeline(transaction=True)
    if anteriores:
        pipe.delete(*anteriores)
    for producto in productos:
        proveedor = proveedores[producto["id_proveedor"]]
        pipe.hset(k_producto(producto["_id"]), mapping=_producto_a_hash(producto, proveedor))
        if producto["activo"]:
            pipe.sadd(K_ACTIVOS, producto["_id"])
    if unidades:
        pipe.zadd(K_RANKING, unidades)
    for fila in ingresos:
        pipe.zadd(k_ingresos(fila["_id"]["mes"]), {fila["_id"]["id_farmaceutico"]: fila["total"]})
    pipe.set(K_OK, "1")
    pipe.execute()

    return {
        "productos": len(productos),
        "productos_activos": sum(1 for p in productos if p["activo"]),
        "productos_en_ranking": len(unidades),
        "meses_con_ingresos": len({fila["_id"]["mes"] for fila in ingresos}),
    }


def asegurar() -> None:
    """Reconstruye las vistas si no están (Redis recién iniciado o vaciado)."""
    if not get_redis().exists(K_OK):
        reconstruir()


def aplicar_venta(venta: dict) -> None:
    """Suma a las vistas una venta 'Completada' ya confirmada en MongoDB.

    Si las vistas no están construidas no hace nada: la próxima reconstrucción ya la incluye.
    """
    r = get_redis()
    if venta["estado"] != "Completada" or not r.exists(K_OK):
        return
    pipe = r.pipeline(transaction=True)
    for item in venta["items"]:
        pipe.zincrby(K_RANKING, item["cantidad"], item["id_producto"])
    pipe.zincrby(k_ingresos(clave_mes(venta["fecha"])), venta["total"], venta["id_farmaceutico"])
    pipe.execute()


if __name__ == "__main__":
    print("Vistas reconstruidas:", reconstruir())
