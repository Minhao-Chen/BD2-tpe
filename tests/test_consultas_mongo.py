"""Pruebas de las consultas nuevas sobre MongoDB."""

from datetime import date

import pytest
from conftest import HOY

from farmared.consultas.q02_ventas_pendientes import ventas_pendientes
from farmared.consultas.q03_historial_cliente import historial_cliente
from farmared.consultas.q04_clientes_con_recetas import clientes_con_recetas
from farmared.consultas.q06_dispensas_vencidas import dispensas_vencidas
from farmared.consultas.q08_lotes_bajo_stock import lotes_bajo_stock
from farmared.consultas.q09_ventas_libres_bajas import ventas_libres_bajas
from farmared.consultas.q10_clientes_por_sucursal import clientes_por_sucursal
from farmared.consultas.q12_clientes_sin_ventas import clientes_sin_ventas
from farmared.errores import ErrorValidacion


def test_q02_ventas_pendientes(base):
    resultado = ventas_pendientes()
    assert [v["id_venta"] for v in resultado] == ["V011", "V012"]
    assert resultado[0]["sucursal"] == {
        "id_sucursal": "S004", "nombre": "Farmacia Nueva Córdoba",
    }


def test_q03_historial_y_cliente_desconocido(base):
    # Se deriva de ventas.csv y recetas.csv de C001; en cada fecha una receta precede a una venta.
    assert [r["id_registro"] for r in historial_cliente("C001")] == [
        "RC001", "V003", "V015", "V013", "RC008", "V010",
    ]
    with pytest.raises(ErrorValidacion):
        historial_cliente("C999")


def test_q04_clientes_con_mas_de_una_receta(base):
    # C001, C002 y C006 tienen dos recetas en recetas.csv.
    assert [(r["id_cliente"], r["cantidad_recetas"]) for r in clientes_con_recetas()] == [
        ("C001", 2), ("C002", 2), ("C006", 2),
    ]


def test_q06_limite_estricto(base):
    assert [r["id_receta"] for r in dispensas_vencidas(hoy=HOY)] == ["RC002", "RC003"]
    assert [r["id_receta"] for r in dispensas_vencidas(hoy=date(2026, 10, 1))] == ["RC002"]


def test_q08_lotes_bajo_stock(base):
    # Son exactamente los lotes con unidades < 50 de stock_lotes.csv, ordenados por unidades.
    assert [l["id_lote"] for l in lotes_bajo_stock(hoy=HOY)] == [
        "L010", "L018", "L003", "L007", "L012", "L002", "L005", "L014", "L011",
    ]
    assert next(l for l in lotes_bajo_stock(hoy=HOY) if l["id_lote"] == "L018")["vencido"] is True


def test_q09_ventas_libres_bajas(base):
    # V013 y V014 son las únicas ventas libres no anuladas con total menor que 5000.
    assert [v["id_venta"] for v in ventas_libres_bajas()] == ["V013", "V014"]


def test_q10_clientes_por_sucursal(base):
    assert [(c["id_cliente"], c["cantidad_ventas"]) for c in clientes_por_sucursal("S001")] == [
        ("C001", 3), ("C006", 4),
    ]
    assert clientes_por_sucursal("S005") == []
    with pytest.raises(ErrorValidacion):
        clientes_por_sucursal("S999")


def test_q12_ventana_y_clientes_sin_ventas(base):
    # Con corte 13/10/2025, V001 queda fuera de la ventana y C008 no tiene ventas.
    assert [c["id_cliente"] for c in clientes_sin_ventas(hoy=HOY)] == ["C004", "C008"]
    # Al mover el corte a 18/09/2026, V001 queda exactamente en el límite y C004 deja de aparecer.
    assert [c["id_cliente"] for c in clientes_sin_ventas(hoy=date(2026, 9, 18))] == ["C008"]
