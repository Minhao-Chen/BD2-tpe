"""q14 — Registro de una nueva venta 'Completada' (cabecera e ítems).

Propósito:
    Registrar una venta con sus ítems, validando las reglas de negocio, actualizando la receta
    (si la hay) y descontando el stock (q15). O queda todo hecho o no queda nada.

Parámetros:
    id_cliente (str): cliente que compra.
    id_farmaceutico (str): farmacéutico que atiende; su sucursal es la de la venta.
    items (list[dict]): [{"id_producto": str, "cantidad": int}, ...]. Si un producto se repite,
        se suman sus cantidades.
    medio_pago (str): Efectivo, Débito, Crédito, Transferencia u Obra social.
    id_receta (str, opcional): receta contra la que se dispensa. Obligatoria si algún producto
        es 'Bajo receta' o 'Bajo receta archivada'.
    hoy (date, opcional): fecha de la venta. Por defecto es la fecha del sistema; solo se pasa
        en los tests.

Validaciones (cualquiera que falle rechaza la venta con ErrorValidacion):
    - hay al menos un ítem, con cantidades enteras mayores a 0; medio de pago válido;
    - el cliente existe y está activo;
    - el farmacéutico existe y está activo, y su sucursal es una 'Farmacia' activa;
    - todos los productos existen y están activos;
    - si hay productos bajo receta: la receta es obligatoria, existe, está 'Vigente', es del
      mismo cliente y le quedan dispensas;
    - si se pasa una receta, la venta debe incluir al menos un producto bajo receta;
    - el stock vigente de la sucursal alcanza para todos los ítems (StockInsuficiente, de q15).

Efectos:
    - Venta 'Completada' con fecha de hoy; precio de cada ítem = precio de lista vigente;
      total = suma de cantidad x precio; tipo 'Con receta' si lleva receta, si no 'Venta libre'.
    - Receta: suma una dispensa. Si llegó a las autorizadas pasa a 'Completada' y
      `proxima_dispensa` queda vacía; si no, `proxima_dispensa` = hoy + 30 días.
    - Stock: descontado por q15 (FEFO, sin lotes vencidos).

Retorno:
    {venta: documento guardado, receta: documento actualizado o None,
     vistas_actualizadas: bool}

Motor:
    MongoDB, una única transacción multi-documento para venta + receta + stock: q15 se ejecuta
    con la misma sesión, así que si el descuento de stock falla, Mongo aborta y no quedan ni la
    venta ni la receta modificadas. Las validaciones leen dentro de la misma transacción.
    Después del commit se suman los totales de la venta a las vistas de Redis (ranking de
    productos e ingresos del mes); si Redis falla, la venta igual queda registrada y
    `vistas_actualizadas` vuelve en False.

Uso:
    make consulta Q=q14 ARGS="--cliente C007 --farmaceutico F006 --receta RC006 --item PRD007:1 --medio-pago Débito"
"""

import argparse
from datetime import date, timedelta

import redis

from farmared import vistas
from farmared.consultas.q15_descontar_stock import descontar_stock
from farmared.db import get_mongo_client, get_mongo_db
from farmared.errores import ErrorValidacion
from farmared.esquema import MEDIOS_PAGO, VENTA_LIBRE
from farmared.fechas import a_datetime, resolver_hoy
from farmared.ids import reservar_ids

DIAS_ENTRE_DISPENSAS = 30


def registrar_venta(
    id_cliente: str,
    id_farmaceutico: str,
    items: list[dict],
    medio_pago: str,
    id_receta: str | None = None,
    hoy: date | None = None,
) -> dict:
    hoy = resolver_hoy(hoy)
    pedido = _normalizar_items(items)
    if medio_pago not in MEDIOS_PAGO:
        raise ErrorValidacion(f"medio de pago {medio_pago!r} inválido; opciones: {', '.join(MEDIOS_PAGO)}")

    db = get_mongo_db()
    ids: dict = {}  # ids reservados una sola vez, aunque la transacción se reintente

    def transaccion(session):
        return _registrar(db, session, ids, id_cliente, id_farmaceutico, pedido, medio_pago, id_receta, hoy)

    with get_mongo_client().start_session() as session:
        resultado = session.with_transaction(transaccion)

    try:
        vistas.aplicar_venta(resultado["venta"])
        resultado["vistas_actualizadas"] = True
    except redis.RedisError:
        resultado["vistas_actualizadas"] = False
    return resultado


def _normalizar_items(items: list[dict]) -> dict[str, int]:
    """Valida la forma de los ítems y devuelve {id_producto: cantidad total}."""
    if not items:
        raise ErrorValidacion("la venta debe tener al menos un ítem")
    pedido: dict[str, int] = {}
    for item in items:
        id_producto = item.get("id_producto")
        cantidad = item.get("cantidad")
        if not isinstance(id_producto, str) or not id_producto:
            raise ErrorValidacion(f"ítem sin id_producto: {item!r}")
        if isinstance(cantidad, bool) or not isinstance(cantidad, int) or cantidad <= 0:
            raise ErrorValidacion(f"la cantidad de {id_producto} debe ser un entero mayor a 0")
        pedido[id_producto] = pedido.get(id_producto, 0) + cantidad
    return pedido


def _registrar(db, session, ids, id_cliente, id_farmaceutico, pedido, medio_pago, id_receta, hoy) -> dict:
    cliente = db.clientes.find_one({"_id": id_cliente}, session=session)
    if cliente is None:
        raise ErrorValidacion(f"el cliente {id_cliente} no existe")
    if not cliente["activo"]:
        raise ErrorValidacion(f"el cliente {id_cliente} está dado de baja")

    farmaceutico = db.farmaceuticos.find_one({"_id": id_farmaceutico}, session=session)
    if farmaceutico is None:
        raise ErrorValidacion(f"el farmacéutico {id_farmaceutico} no existe")
    if not farmaceutico["activo"]:
        raise ErrorValidacion(f"el farmacéutico {id_farmaceutico} no está activo")

    id_sucursal = farmaceutico["id_sucursal"]
    sucursal = db.sucursales.find_one({"_id": id_sucursal}, session=session)
    if sucursal is None or sucursal["tipo"] != "Farmacia":
        raise ErrorValidacion(f"la sucursal {id_sucursal} no es una Farmacia: no registra ventas")
    if not sucursal["activo"]:
        raise ErrorValidacion(f"la sucursal {id_sucursal} no está habilitada")

    productos = {
        p["_id"]: p
        for p in db.productos.find({"_id": {"$in": list(pedido)}}, session=session)
    }
    inexistentes = [i for i in pedido if i not in productos]
    if inexistentes:
        raise ErrorValidacion(f"productos inexistentes: {', '.join(inexistentes)}")
    inactivos = [i for i in pedido if not productos[i]["activo"]]
    if inactivos:
        raise ErrorValidacion(f"productos discontinuados: {', '.join(inactivos)}")

    bajo_receta = [i for i in pedido if productos[i]["condicion_venta"] != VENTA_LIBRE]
    receta = None
    if bajo_receta and id_receta is None:
        raise ErrorValidacion(f"se requiere receta para: {', '.join(bajo_receta)}")
    if id_receta is not None:
        receta = db.recetas.find_one({"_id": id_receta}, session=session)
        if receta is None:
            raise ErrorValidacion(f"la receta {id_receta} no existe")
        if receta["id_cliente"] != id_cliente:
            raise ErrorValidacion(f"la receta {id_receta} no pertenece al cliente {id_cliente}")
        if receta["estado"] != "Vigente":
            raise ErrorValidacion(f"la receta {id_receta} está {receta['estado']}, no Vigente")
        if receta["dispensas_realizadas"] >= receta["dispensas_autorizadas"]:
            raise ErrorValidacion(f"la receta {id_receta} no tiene dispensas disponibles")
        if not bajo_receta:
            raise ErrorValidacion(
                f"la venta no incluye productos bajo receta: no corresponde usar la receta {id_receta}"
            )

    if not ids:
        ids["venta"] = reservar_ids(db, "ventas")[0]
        ids["detalles"] = reservar_ids(db, "detalles", len(pedido))

    items = [
        {
            "id_detalle": id_detalle,
            "id_producto": id_producto,
            "cantidad": cantidad,
            "precio_unit": productos[id_producto]["precio_unit"],
        }
        for id_detalle, (id_producto, cantidad) in zip(ids["detalles"], pedido.items())
    ]
    venta = {
        "_id": ids["venta"],
        "id_cliente": id_cliente,
        "id_farmaceutico": id_farmaceutico,
        "id_sucursal": id_sucursal,
        "id_receta": id_receta,
        "fecha": a_datetime(hoy),
        "tipo": "Con receta" if id_receta is not None else "Venta libre",
        "medio_pago": medio_pago,
        "total": sum(i["cantidad"] * i["precio_unit"] for i in items),
        "estado": "Completada",
        "items": items,
        "stock_aplicado": False,
        "lotes_consumidos": [],
    }
    db.ventas.insert_one(venta, session=session)

    if receta is not None:
        _registrar_dispensa(db, session, receta, hoy)

    descontar_stock(venta["_id"], hoy=hoy, session=session)

    return {
        "venta": db.ventas.find_one({"_id": venta["_id"]}, session=session),
        "receta": db.recetas.find_one({"_id": id_receta}, session=session) if receta else None,
    }


def _registrar_dispensa(db, session, receta: dict, hoy: date) -> None:
    """Suma una dispensa a la receta y actualiza estado y próxima dispensa."""
    realizadas = receta["dispensas_realizadas"] + 1
    if realizadas >= receta["dispensas_autorizadas"]:
        cambios = {"dispensas_realizadas": realizadas, "estado": "Completada", "proxima_dispensa": None}
    else:
        cambios = {
            "dispensas_realizadas": realizadas,
            "proxima_dispensa": a_datetime(hoy + timedelta(days=DIAS_ENTRE_DISPENSAS)),
        }
    resultado = db.recetas.update_one(
        # El filtro repite lo que se leyó: si otra operación ya usó la receta, no coincide.
        {"_id": receta["_id"], "estado": "Vigente", "dispensas_realizadas": receta["dispensas_realizadas"]},
        {"$set": cambios},
        session=session,
    )
    if resultado.modified_count != 1:
        raise ErrorValidacion(f"la receta {receta['_id']} fue modificada por otra operación")


def _item(texto: str) -> dict:
    """Convierte 'PRD007:2' en un ítem."""
    id_producto, separador, cantidad = texto.partition(":")
    if not separador or not cantidad.isdigit():
        raise argparse.ArgumentTypeError(f"{texto!r}: se esperaba PRODUCTO:CANTIDAD, p. ej. PRD007:2")
    return {"id_producto": id_producto, "cantidad": int(cantidad)}


def cli(argv: list[str]) -> dict:
    parser = argparse.ArgumentParser(prog="q14", description="Registra una venta Completada.")
    parser.add_argument("--cliente", required=True, help="id del cliente, p. ej. C007")
    parser.add_argument("--farmaceutico", required=True, help="id del farmacéutico, p. ej. F006")
    parser.add_argument("--item", required=True, action="append", type=_item,
                        metavar="PRODUCTO:CANTIDAD", help="se puede repetir, p. ej. --item PRD007:1")
    parser.add_argument("--medio-pago", required=True, choices=MEDIOS_PAGO)
    parser.add_argument("--receta", default=None, help="id de la receta, p. ej. RC006")
    args = parser.parse_args(argv)
    return registrar_venta(args.cliente, args.farmaceutico, args.item, args.medio_pago, args.receta)
