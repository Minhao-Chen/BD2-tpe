"""Tests sobre los registros adicionales reales (`data/extra/`).

El resto de los tests carga solo los CSV originales. Estos cargan además `data/extra/` tal cual
está en el repo, así que fallan si alguien rompe un CSV adicional (la carga no lo valida) o si un
cambio hace que un registro deje de cubrir el caso borde para el que fue escrito.

Cada test corre dos veces: con "hoy" = FECHA_REFERENCIA (las fechas quedan como están escritas)
y con "hoy" casi cuatro meses después (las fechas adicionales se desplazan). Los casos borde
tienen que mantenerse en los dos. El segundo día cae antes del 24 del mes a propósito: así las
únicas ventas Completadas del mes actual son las escritas con la fecha de referencia (q11).
"""

from datetime import date

import pytest
from conftest import foto

from farmared import config
from farmared.carga.cargador import cargar, leer_fecha_referencia
from farmared.consultas.q02_ventas_pendientes import ventas_pendientes
from farmared.consultas.q03_historial_cliente import historial_cliente
from farmared.consultas.q04_clientes_con_recetas import clientes_con_recetas
from farmared.consultas.q05_ventas_por_farmaceutico import ventas_por_farmaceutico
from farmared.consultas.q06_dispensas_vencidas import dispensas_vencidas
from farmared.consultas.q07_top_productos import top_productos
from farmared.consultas.q08_lotes_bajo_stock import lotes_bajo_stock
from farmared.consultas.q09_ventas_libres_bajas import ventas_libres_bajas
from farmared.consultas.q10_clientes_por_sucursal import clientes_por_sucursal
from farmared.consultas.q11_ingresos_por_farmaceutico import ingresos_por_farmaceutico
from farmared.consultas.q12_clientes_sin_ventas import clientes_sin_ventas
from farmared.consultas.q14_registrar_venta import registrar_venta
from farmared.db import get_mongo_db
from farmared.errores import ErrorValidacion, StockInsuficiente

REFERENCIA = leer_fecha_referencia(config.DIR_ADICIONALES)


@pytest.fixture(params=[REFERENCIA, date(2027, 3, 5)], ids=["referencia", "desplazado"])
def hoy(request, entorno) -> date:
    """Carga originales + `data/extra/` tomando `request.param` como fecha del sistema."""
    resumen = cargar(hoy=request.param)
    assert resumen["filas_adicionales"] >= 90  # 10 por colección + ítems de venta
    return request.param


def test_cada_coleccion_tiene_al_menos_10_registros_adicionales(entorno):
    resumen_original = cargar(dir_adicionales=config.DIR_ORIGINALES.parent / "no_existe")
    resumen_total = cargar(hoy=REFERENCIA)
    for coleccion, total in resumen_total["colecciones"].items():
        assert total - resumen_original["colecciones"][coleccion] >= 10, coleccion


def test_q02_incluye_las_pendientes_adicionales(hoy):
    assert {"V024", "V033"} <= {v["id_venta"] for v in ventas_pendientes()}


def test_q03_receta_antes_que_venta_el_mismo_dia(hoy):
    historial = [(r["tipo_registro"], r["id_registro"]) for r in historial_cliente("C009")]
    assert historial.index(("receta", "RC010")) + 1 == historial.index(("venta", "V017"))


def test_q04_limite_de_mas_de_una_receta(hoy):
    cantidades = {c["id_cliente"]: c["cantidad_recetas"] for c in clientes_con_recetas()}
    assert cantidades["C009"] == 3
    assert cantidades["C010"] == 2
    assert "C011" not in cantidades  # tiene una sola


def test_q05_ventana_de_60_dias(hoy):
    cantidades = {f["id_farmaceutico"]: f["cantidad_ventas"] for f in ventas_por_farmaceutico(hoy)}
    assert cantidades["F016"] == 1  # V028 a 60 días justos; V029 (61) y V027 (Anulada) no
    assert cantidades["F009"] == 2  # incluye V033, Pendiente
    assert cantidades["F008"] == 1  # V018 sí, V017 (75 días) no
    assert cantidades["F013"] == 0  # activo sin ventas
    assert "F014" not in cantidades  # inactivo, aunque tenga ventas recientes


def test_q06_proxima_dispensa_estrictamente_anterior_a_hoy(hoy):
    ids = {r["id_receta"] for r in dispensas_vencidas(hoy)}
    assert "RC010" in ids  # ayer
    assert "RC011" not in ids  # hoy
    assert "RC013" not in ids  # mañana


def test_q07_no_cuenta_pendientes_ni_anuladas(hoy):
    ranking = top_productos()
    assert ranking[0] == {"id_producto": "PRD015", "nombre": "Enalapril 10mg x30", "unidades": 7}
    # PRD020 tiene 3 unidades Completadas; las 20 de V033 (Pendiente) no deben sumar.
    # PRD017 tiene 3; las 30 de V034 (Anulada) no deben sumar.
    assert all(p["id_producto"] not in ("PRD020", "PRD017") for p in ranking)


def test_q08_limite_de_50_unidades_y_vencidos(hoy):
    lotes = {lote["id_lote"]: lote for lote in lotes_bajo_stock(hoy)}
    assert lotes["L022"]["unidades"] == 49
    assert "L023" not in lotes  # 50 unidades
    assert lotes["L024"]["unidades"] == 0
    assert lotes["L019"]["vencido"] is True
    assert lotes["L025"]["vencido"] is False  # vence en 7 días


def test_q09_limite_de_5000(hoy):
    ids = {v["id_venta"] for v in ventas_libres_bajas()}
    assert {"V025", "V028"} <= ids  # 4.999 y 3.100
    assert "V026" not in ids  # 5.000
    assert "V027" not in ids  # Anulada


def test_q10_sucursal_de_baja_y_sucursal_sin_ventas(hoy):
    assert [c["id_cliente"] for c in clientes_por_sucursal("S012")] == ["C018"]
    assert clientes_por_sucursal("S013") == []


def test_q11_ingresos_del_mes_actual(hoy):
    ingresos = {f["id_farmaceutico"]: f["ingresos"] for f in ingresos_por_farmaceutico(hoy)}
    assert ingresos == {"F012": 9999, "F011": 8600, "F010": 6800}


def test_q12_limite_de_un_anio(hoy):
    ids = {c["id_cliente"] for c in clientes_sin_ventas(hoy)}
    assert {"C013", "C014", "C015"} <= ids  # 1 año + 1 día, sin ventas, inactivo sin ventas
    assert "C012" not in ids  # última venta hace 1 año justo


def test_q14_fefo_saltea_el_lote_vencido_y_completa_la_receta(hoy):
    resultado = registrar_venta(
        "C017", "F008", [{"id_producto": "PRD015", "cantidad": 5}], "Obra social", "RC016", hoy=hoy
    )
    assert resultado["venta"]["lotes_consumidos"] == [
        {"id_lote": "L020", "id_producto": "PRD015", "unidades": 3},
        {"id_lote": "L021", "id_producto": "PRD015", "unidades": 2},
    ]
    assert resultado["receta"]["estado"] == "Completada"
    assert resultado["receta"]["proxima_dispensa"] is None
    assert get_mongo_db().stock_lotes.find_one({"_id": "L019"})["unidades"] == 30


def test_q14_sin_stock_en_un_item_no_modifica_nada(hoy):
    db = get_mongo_db()
    antes = foto(db)
    with pytest.raises(StockInsuficiente):
        registrar_venta(
            "C011", "F008",
            [{"id_producto": "PRD018", "cantidad": 2}, {"id_producto": "PRD019", "cantidad": 1}],
            "Débito", "RC015", hoy=hoy,
        )
    assert foto(db) == antes


@pytest.mark.parametrize("cliente, items, receta, motivo", [
    ("C009", [("PRD015", 1)], "RC012", "Vencida"),
    ("C015", [("PRD014", 1)], None, "dado de baja"),
    ("C018", [("PRD023", 1)], None, "discontinuados"),
    ("C018", [("PRD018", 1)], None, "se requiere receta"),
])
def test_q14_rechazos_con_los_datos_adicionales(hoy, cliente, items, receta, motivo):
    db = get_mongo_db()
    antes = foto(db)
    with pytest.raises(ErrorValidacion, match=motivo):
        registrar_venta(
            cliente, "F008", [{"id_producto": p, "cantidad": c} for p, c in items],
            "Efectivo", receta, hoy=hoy,
        )
    assert foto(db) == antes
