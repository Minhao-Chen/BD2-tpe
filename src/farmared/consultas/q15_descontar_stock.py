"""q15 — Actualización masiva del stock de una venta registrada (FEFO).

Propósito:
    Dada una venta ya registrada, descontar las unidades de cada producto de su detalle en los
    lotes de la sucursal donde se hizo la venta (la del farmacéutico). Se consume primero el lote
    que vence antes (FEFO) y se saltean los lotes vencidos. Si el stock vigente no alcanza para
    algún ítem, se rechaza todo y no se modifica ningún lote.

Parámetros:
    id_venta (str): venta cuyo detalle se descuenta. Debe existir, estar 'Completada' y no
        tener el stock ya descontado.
    hoy (date, opcional): día contra el que se decide si un lote está vencido. Por defecto es
        la fecha del sistema; solo se pasa en los tests. Un lote sirve si vencimiento >= hoy.
    session (ClientSession, opcional): sesión con una transacción ya abierta. La usa q14 para
        que venta, receta y stock se confirmen o se descarten juntos. Si no se pasa, la función
        abre su propia transacción.

Retorno:
    {id_venta, id_sucursal, lotes_consumidos: [{id_lote, id_producto, unidades}]}
    en el orden en que se consumieron los lotes.

Errores:
    ErrorValidacion: la venta no existe, no está 'Completada' o ya fue descontada.
    StockInsuficiente: falta stock vigente; `faltantes` detalla producto, pedido y disponible.

Motor:
    MongoDB, dentro de una transacción multi-documento. Pasos:
    1. Lee los lotes vigentes de la sucursal y arma el plan completo de consumo. Si falta stock
       para algún producto, rechaza antes de escribir.
    2. Aplica cada paso con una actualización condicional (`unidades >= n`), que nunca puede
       dejar un lote en negativo.
    3. Marca la venta con `stock_aplicado = true` y guarda los lotes consumidos.
    Si dos ventas compiten por el mismo lote, Mongo detecta el conflicto de escritura y la
    transacción se reintenta con los datos nuevos.

Uso:
    make consulta Q=q15 ARGS="V011"   (rechazo: está Pendiente; ver README)
"""

import argparse
from collections import defaultdict
from datetime import date

from farmared.db import get_mongo_client, get_mongo_db
from farmared.errores import ErrorValidacion, StockInsuficiente
from farmared.fechas import a_datetime, resolver_hoy


def planificar_fefo(pedido: dict[str, int], lotes: list[dict]) -> tuple[list[dict], list[dict]]:
    """Reparte las unidades pedidas entre los lotes, del que vence antes al que vence después.

    Parámetros:
        pedido: {id_producto: unidades}.
        lotes: lotes disponibles (ya filtrados por sucursal y sin vencidos), con `_id`,
            `id_producto`, `unidades` y `vencimiento`.
    Retorna (plan, faltantes):
        plan: [{id_lote, id_producto, unidades}] a descontar.
        faltantes: [{id_producto, solicitado, disponible}] de los productos que no alcanzan.
    """
    por_producto: dict[str, list[dict]] = defaultdict(list)
    for lote in sorted(lotes, key=lambda lote: (lote["vencimiento"], lote["_id"])):
        por_producto[lote["id_producto"]].append(lote)

    plan: list[dict] = []
    faltantes: list[dict] = []
    for id_producto, solicitado in pedido.items():
        restante = solicitado
        for lote in por_producto[id_producto]:
            if restante == 0:
                break
            usar = min(restante, lote["unidades"])
            if usar > 0:
                plan.append({"id_lote": lote["_id"], "id_producto": id_producto, "unidades": usar})
                restante -= usar
        if restante > 0:
            faltantes.append({
                "id_producto": id_producto,
                "solicitado": solicitado,
                "disponible": solicitado - restante,
            })
    return plan, faltantes


def descontar_stock(id_venta: str, hoy: date | None = None, session=None) -> dict:
    hoy = resolver_hoy(hoy)
    db = get_mongo_db()
    if session is not None:
        return _descontar(db, session, id_venta, hoy)
    with get_mongo_client().start_session() as propia:
        return propia.with_transaction(lambda s: _descontar(db, s, id_venta, hoy))


def _descontar(db, session, id_venta: str, hoy: date) -> dict:
    venta = db.ventas.find_one({"_id": id_venta}, session=session)
    if venta is None:
        raise ErrorValidacion(f"la venta {id_venta} no existe")
    if venta["estado"] != "Completada":
        raise ErrorValidacion(
            f"la venta {id_venta} está {venta['estado']}: solo las Completadas descuentan stock"
        )
    if venta["stock_aplicado"]:
        raise ErrorValidacion(f"la venta {id_venta} ya tiene el stock descontado")

    pedido: dict[str, int] = defaultdict(int)
    for item in venta["items"]:
        pedido[item["id_producto"]] += item["cantidad"]

    lotes = list(db.stock_lotes.find(
        {
            "id_sucursal": venta["id_sucursal"],
            "id_producto": {"$in": list(pedido)},
            "vencimiento": {"$gte": a_datetime(hoy)},
            "unidades": {"$gt": 0},
        },
        session=session,
    ))
    plan, faltantes = planificar_fefo(pedido, lotes)
    if faltantes:
        raise StockInsuficiente(faltantes)

    for paso in plan:
        resultado = db.stock_lotes.update_one(
            {"_id": paso["id_lote"], "unidades": {"$gte": paso["unidades"]}},
            {"$inc": {"unidades": -paso["unidades"]}},
            session=session,
        )
        if resultado.modified_count != 1:
            # El lote cambió entre la lectura y la escritura: se aborta todo.
            raise StockInsuficiente([{
                "id_producto": paso["id_producto"],
                "solicitado": pedido[paso["id_producto"]],
                "disponible": 0,
            }])

    db.ventas.update_one(
        {"_id": id_venta},
        {"$set": {"stock_aplicado": True, "lotes_consumidos": plan}},
        session=session,
    )
    return {"id_venta": id_venta, "id_sucursal": venta["id_sucursal"], "lotes_consumidos": plan}


def cli(argv: list[str]) -> dict:
    parser = argparse.ArgumentParser(prog="q15", description="Descuenta el stock de una venta (FEFO).")
    parser.add_argument("id_venta", help="id de la venta, por ejemplo V017")
    args = parser.parse_args(argv)
    return descontar_stock(args.id_venta)
