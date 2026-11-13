"""Tests de los servicios de escritura q14 (registrar venta) y q15 (descontar stock)."""

from datetime import date, datetime
from threading import Thread

import pytest
from conftest import HOY, foto

from farmared import vistas
from farmared.consultas.q14_registrar_venta import registrar_venta
from farmared.consultas.q15_descontar_stock import descontar_stock, planificar_fefo
from farmared.db import get_redis
from farmared.errores import ErrorValidacion, StockInsuficiente


def item(id_producto: str, cantidad: int) -> dict:
    return {"id_producto": id_producto, "cantidad": cantidad}


def unidades(db, id_lote: str) -> int:
    return db.stock_lotes.find_one({"_id": id_lote})["unidades"]


# --- FEFO, sin base de datos ------------------------------------------------------------------

def lote(id_lote, producto, cantidad, vencimiento):
    return {"_id": id_lote, "id_producto": producto, "unidades": cantidad, "vencimiento": vencimiento}


def test_fefo_consume_primero_el_lote_que_vence_antes():
    lotes = [lote("L2", "P1", 100, date(2027, 6, 30)), lote("L1", "P1", 40, date(2026, 11, 30))]
    plan, faltantes = planificar_fefo({"P1": 45}, lotes)
    assert plan == [
        {"id_lote": "L1", "id_producto": "P1", "unidades": 40},
        {"id_lote": "L2", "id_producto": "P1", "unidades": 5},
    ]
    assert faltantes == []


def test_fefo_informa_todos_los_faltantes():
    lotes = [lote("L1", "P1", 10, date(2027, 1, 1))]
    plan, faltantes = planificar_fefo({"P1": 12, "P2": 1}, lotes)
    assert faltantes == [
        {"id_producto": "P1", "solicitado": 12, "disponible": 10},
        {"id_producto": "P2", "solicitado": 1, "disponible": 0},
    ]


# --- q14: ventas aceptadas --------------------------------------------------------------------

def test_venta_libre(base):
    resultado = registrar_venta("C005", "F005", [item("PRD001", 2)], "Efectivo", hoy=HOY)

    venta = base.ventas.find_one({"_id": "V017"})
    assert resultado["venta"] == venta
    assert resultado["receta"] is None
    assert venta["estado"] == "Completada"
    assert venta["tipo"] == "Venta libre"
    assert venta["id_sucursal"] == "S003"
    assert venta["fecha"] == datetime(2026, 10, 13)
    assert venta["items"] == [
        {"id_detalle": "D023", "id_producto": "PRD001", "cantidad": 2, "precio_unit": 2800}
    ]
    assert venta["total"] == 5600
    assert venta["stock_aplicado"] is True
    assert venta["lotes_consumidos"] == [{"id_lote": "L003", "id_producto": "PRD001", "unidades": 2}]
    assert unidades(base, "L003") == 16


def test_items_repetidos_se_suman(base):
    registrar_venta("C005", "F005", [item("PRD001", 2), item("PRD001", 3)], "Efectivo", hoy=HOY)
    venta = base.ventas.find_one({"_id": "V017"})
    assert [(i["id_producto"], i["cantidad"]) for i in venta["items"]] == [("PRD001", 5)]
    assert unidades(base, "L003") == 13


def test_receta_simple_se_completa(base):
    resultado = registrar_venta("C007", "F006", [item("PRD007", 1)], "Débito", id_receta="RC006", hoy=HOY)

    assert resultado["venta"]["tipo"] == "Con receta"
    assert resultado["venta"]["total"] == 4800
    receta = base.recetas.find_one({"_id": "RC006"})
    assert (receta["dispensas_realizadas"], receta["estado"], receta["proxima_dispensa"]) == (1, "Completada", None)
    assert unidades(base, "L014") == 44


def test_tratamiento_prolongado_fija_proxima_dispensa_a_30_dias(base):
    registrar_venta("C006", "F001", [item("PRD006", 1)], "Obra social", id_receta="RC004", hoy=HOY)
    receta = base.recetas.find_one({"_id": "RC004"})
    assert (receta["dispensas_realizadas"], receta["estado"]) == (2, "Vigente")
    assert receta["proxima_dispensa"] == datetime(2026, 11, 12)  # 13/10 + 30 días


def test_tratamiento_prolongado_se_completa_en_la_ultima_dispensa(base):
    registrar_venta("C003", "F006", [item("PRD004", 1)], "Obra social", id_receta="RC002", hoy=HOY)
    receta = base.recetas.find_one({"_id": "RC002"})
    assert (receta["dispensas_realizadas"], receta["estado"], receta["proxima_dispensa"]) == (3, "Completada", None)


def test_fefo_usa_varios_lotes(base):
    registrar_venta("C007", "F001", [item("PRD003", 45)], "Efectivo", id_receta="RC006", hoy=HOY)
    # S001 tiene L005 (40 u., vence 30/11/2026) y L015 (100 u., vence 30/06/2027).
    assert (unidades(base, "L005"), unidades(base, "L015")) == (0, 95)
    assert base.ventas.find_one({"_id": "V017"})["lotes_consumidos"] == [
        {"id_lote": "L005", "id_producto": "PRD003", "unidades": 40},
        {"id_lote": "L015", "id_producto": "PRD003", "unidades": 5},
    ]


def test_fefo_saltea_lotes_vencidos(base):
    # El 01/12/2026 el lote L005 (vence 30/11) ya está vencido.
    registrar_venta("C007", "F001", [item("PRD003", 45)], "Efectivo", id_receta="RC006", hoy=date(2026, 12, 1))
    assert (unidades(base, "L005"), unidades(base, "L015")) == (40, 55)


def test_lote_que_vence_hoy_todavia_se_dispensa(base):
    registrar_venta("C007", "F001", [item("PRD003", 1)], "Efectivo", id_receta="RC006", hoy=date(2026, 11, 30))
    assert unidades(base, "L005") == 39


def test_la_venta_actualiza_las_vistas_de_redis(base):
    r = get_redis()
    registrar_venta("C005", "F005", [item("PRD001", 2)], "Efectivo", hoy=HOY)

    assert r.zscore(vistas.K_RANKING, "PRD001") == 6  # 4 del historial + 2
    assert r.zscore(vistas.k_ingresos("2026-10"), "F005") == 10200  # 4600 + 5600
    incremental = r.zrange(vistas.K_RANKING, 0, -1, withscores=True)
    vistas.reconstruir()
    assert r.zrange(vistas.K_RANKING, 0, -1, withscores=True) == incremental


# --- q14: rechazos (no debe cambiar nada) -------------------------------------------------------

RECHAZOS = {
    "sin ítems": (("C005", "F005", [], "Efectivo"), {}, "al menos un ítem"),
    "cantidad cero": (("C005", "F005", [item("PRD001", 0)], "Efectivo"), {}, "entero mayor a 0"),
    "medio de pago inválido": (("C005", "F005", [item("PRD001", 1)], "Cheque"), {}, "medio de pago"),
    "cliente inexistente": (("C999", "F005", [item("PRD001", 1)], "Efectivo"), {}, "cliente C999 no existe"),
    "cliente dado de baja": (("C008", "F005", [item("PRD001", 1)], "Efectivo"), {}, "dado de baja"),
    "farmacéutico inexistente": (("C005", "F999", [item("PRD001", 1)], "Efectivo"), {}, "F999 no existe"),
    "farmacéutico inactivo": (("C005", "F004", [item("PRD001", 1)], "Efectivo"), {}, "no está activo"),
    "farmacéutico de la droguería": (("C005", "F007", [item("PRD001", 1)], "Efectivo"), {}, "no es una Farmacia"),
    "producto inexistente": (("C005", "F005", [item("PRD999", 1)], "Efectivo"), {}, "inexistentes: PRD999"),
    "producto discontinuado": (("C005", "F003", [item("PRD012", 1)], "Efectivo"), {}, "discontinuados: PRD012"),
    "bajo receta sin receta": (("C001", "F001", [item("PRD003", 1)], "Efectivo"), {}, "se requiere receta"),
    "receta inexistente": (("C001", "F001", [item("PRD003", 1)], "Efectivo"), {"id_receta": "RC999"}, "RC999 no existe"),
    "receta de otro cliente": (("C001", "F001", [item("PRD003", 1)], "Efectivo"), {"id_receta": "RC006"}, "no pertenece"),
    "receta vencida": (("C002", "F001", [item("PRD003", 1)], "Efectivo"), {"id_receta": "RC009"}, "está Vencida"),
    "receta completada": (("C001", "F001", [item("PRD003", 1)], "Efectivo"), {"id_receta": "RC001"}, "está Completada"),
    "receta sin productos bajo receta": (("C007", "F001", [item("PRD001", 1)], "Efectivo"), {"id_receta": "RC006"}, "no corresponde"),
}


@pytest.mark.parametrize("caso", RECHAZOS)
def test_rechazos_de_validacion(base, caso):
    args, kwargs, mensaje = RECHAZOS[caso]
    antes = foto(base)
    with pytest.raises(ErrorValidacion, match=mensaje):
        registrar_venta(*args, hoy=HOY, **kwargs)
    assert foto(base) == antes


def test_stock_insuficiente_no_deja_venta_ni_receta_ni_lotes_modificados(base):
    antes = foto(base)
    # PRD007 alcanza (45 u.) pero PRD004 no (22 u.): se rechaza la venta entera.
    with pytest.raises(StockInsuficiente) as error:
        registrar_venta(
            "C007", "F006", [item("PRD007", 1), item("PRD004", 23)], "Débito", id_receta="RC006", hoy=HOY
        )
    assert error.value.faltantes == [{"id_producto": "PRD004", "solicitado": 23, "disponible": 22}]
    assert foto(base) == antes


def test_stock_solo_vencido_se_rechaza(base):
    antes = foto(base)
    # El único lote de PRD010 en S002 (L012) vence el 31/10/2026.
    with pytest.raises(StockInsuficiente):
        registrar_venta(
            "C007", "F003", [item("PRD010", 1)], "Efectivo", id_receta="RC006", hoy=date(2026, 11, 13)
        )
    assert foto(base) == antes


def test_dos_ventas_simultaneas_no_dejan_stock_negativo(base):
    # L003 tiene 18 unidades de PRD001 en S003: dos ventas de 10 no entran las dos.
    resultados = []

    def vender(id_cliente):
        try:
            registrar_venta(id_cliente, "F005", [item("PRD001", 10)], "Efectivo", hoy=HOY)
            resultados.append("ok")
        except StockInsuficiente:
            resultados.append("sin stock")

    hilos = [Thread(target=vender, args=(c,)) for c in ("C005", "C001")]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert sorted(resultados) == ["ok", "sin stock"]
    assert unidades(base, "L003") == 8
    assert base.ventas.count_documents({}) == 17


# --- q15 por separado ---------------------------------------------------------------------------

def venta_sin_descontar() -> dict:
    return {
        "_id": "V900", "id_cliente": "C005", "id_farmaceutico": "F005", "id_sucursal": "S003",
        "id_receta": None, "fecha": datetime(2026, 10, 13), "tipo": "Venta libre",
        "medio_pago": "Efectivo", "total": 5600, "estado": "Completada",
        "items": [{"id_detalle": "D900", "id_producto": "PRD001", "cantidad": 2, "precio_unit": 2800}],
        "stock_aplicado": False, "lotes_consumidos": [],
    }


def test_q15_descuenta_una_venta_registrada_y_no_lo_repite(base):
    base.ventas.insert_one(venta_sin_descontar())

    resultado = descontar_stock("V900", hoy=HOY)

    assert resultado == {
        "id_venta": "V900", "id_sucursal": "S003",
        "lotes_consumidos": [{"id_lote": "L003", "id_producto": "PRD001", "unidades": 2}],
    }
    assert unidades(base, "L003") == 16
    with pytest.raises(ErrorValidacion, match="ya tiene el stock descontado"):
        descontar_stock("V900", hoy=HOY)
    assert unidades(base, "L003") == 16


def test_q15_rechaza_sin_modificar_lotes_si_no_alcanza(base):
    venta = venta_sin_descontar()
    venta["items"][0]["cantidad"] = 19  # hay 18
    base.ventas.insert_one(venta)
    antes = foto(base)
    with pytest.raises(StockInsuficiente):
        descontar_stock("V900", hoy=HOY)
    assert foto(base) == antes


@pytest.mark.parametrize("id_venta, mensaje", [
    ("V999", "no existe"),
    ("V011", "está Pendiente"),
    ("V015", "está Anulada"),
    ("V003", "ya tiene el stock descontado"),
])
def test_q15_rechaza_ventas_que_no_corresponde_descontar(base, id_venta, mensaje):
    antes = foto(base)
    with pytest.raises(ErrorValidacion, match=mensaje):
        descontar_stock(id_venta, hoy=HOY)
    assert foto(base) == antes
