"""Tests de la carga: lectura, validación, modelo resultante, idempotencia y desplazamiento."""

import copy
from datetime import date, datetime

import pytest
from conftest import HOY

from farmared import config
from farmared.carga.cargador import cargar
from farmared.carga.lector import leer_directorio
from farmared.carga.validacion import validar
from farmared.errores import ErrorCarga

CANTIDADES = {
    "clientes": 8, "sucursales": 5, "farmaceuticos": 7, "proveedores": 5, "productos": 13,
    "stock_lotes": 18, "recetas": 9, "ventas": 16,
}


# --- Sin base de datos ----------------------------------------------------------------------

@pytest.fixture
def originales():
    return leer_directorio(config.DIR_ORIGINALES, obligatorio=True)


def test_los_csv_originales_son_validos(originales):
    assert validar(originales) == []


def test_lectura_convierte_tipos_y_vacios(originales):
    c005 = next(c for c in originales["clientes"] if c["id_cliente"] == "C005")
    assert c005["nro_afiliado"] is None
    assert c005["activo"] is True
    rc002 = next(r for r in originales["recetas"] if r["id_receta"] == "RC002")
    assert rc002["proxima_dispensa"] == date(2026, 9, 15)
    assert rc002["dispensas_autorizadas"] == 3
    prd008 = next(p for p in originales["productos"] if p["id_producto"] == "PRD008")
    assert prd008["nombre"] == "Alprazolam 0,5mg x30"  # coma dentro de un campo entre comillas


@pytest.mark.parametrize("romper, texto_esperado", [
    (lambda d: d["farmaceuticos"][0].update(id_sucursal="S999"), "no existe en sucursales"),
    (lambda d: d["ventas"][0].update(total=1), "distinto de la suma"),
    (lambda d: d["clientes"][1].update(dni=d["clientes"][0]["dni"]), "aparece 2 veces"),
    (lambda d: d["ventas"][0].update(estado="Cancelada"), "no es un valor permitido"),
    (lambda d: d["recetas"][0].update(dispensas_realizadas=0, estado="Vigente"), "venta(s) Completada(s)"),
    (lambda d: d["clientes"][0].update(nro_afiliado=None), "Sin cobertura"),
    (lambda d: d["ventas"][1].update(id_farmaceutico="F007"), "no es de una Farmacia"),
])
def test_validacion_detecta_errores(originales, romper, texto_esperado):
    datos = copy.deepcopy(originales)
    romper(datos)
    errores = validar(datos)
    assert any(texto_esperado in e for e in errores), errores


# --- Con base de datos ----------------------------------------------------------------------

def test_carga_cantidades_y_modelo(base):
    assert {c: base[c].count_documents({}) for c in CANTIDADES} == CANTIDADES

    v006 = base.ventas.find_one({"_id": "V006"})
    assert [i["id_detalle"] for i in v006["items"]] == ["D007", "D008"]
    assert v006["id_sucursal"] == "S001"  # la sucursal del farmacéutico F002
    assert v006["fecha"] == datetime(2026, 8, 1)
    assert v006["stock_aplicado"] is True  # Completada: ya reflejada en el stock cargado
    assert base.ventas.find_one({"_id": "V011"})["stock_aplicado"] is False  # Pendiente

    total_items = sum(len(v["items"]) for v in base.ventas.find())
    assert total_items == 22

    c001 = base.clientes.find_one({"_id": "C001"})
    assert c001["cobertura"] == {"obra_social": "OSDE", "nro_afiliado": "OS-310045"}

    contadores = {c["_id"]: c["seq"] for c in base.contadores.find()}
    assert contadores == {"clientes": 8, "ventas": 16, "detalles": 22}


def test_carga_es_idempotente(base, tmp_path):
    def estado():
        return {c: list(base[c].find().sort("_id", 1)) for c in [*CANTIDADES, "contadores"]}

    antes = estado()
    cargar(hoy=HOY, dir_adicionales=tmp_path)
    assert estado() == antes


def test_carga_invalida_no_escribe_nada(base, tmp_path):
    (tmp_path / "farmaceuticos.csv").write_text(
        "id_farmaceutico,nombre,apellido,matricula,cargo,id_sucursal,activo\n"
        "F900,Ana,Prueba,MN-90000,Farmacéutico,S999,True\n",
        encoding="utf-8",
    )
    with pytest.raises(ErrorCarga, match="no existe en sucursales"):
        cargar(hoy=HOY, dir_adicionales=tmp_path, desplazar=False)
    assert base.farmaceuticos.count_documents({}) == 7


def test_fechas_adicionales_se_desplazan(base, tmp_path):
    (tmp_path / "FECHA_REFERENCIA").write_text("# comentario\n2026-11-13\n", encoding="utf-8")
    (tmp_path / "stock_lotes.csv").write_text(
        "id_lote,id_producto,id_sucursal,nro_lote,unidades,vencimiento\n"
        "L900,PRD001,S001,X-1,10,2026-11-20\n",
        encoding="utf-8",
    )
    # Referencia 13/11 y "hoy" 13/12: todo lo adicional se mueve 30 días.
    resumen = cargar(hoy=date(2026, 12, 13), dir_adicionales=tmp_path)
    assert resumen["dias_desplazados"] == 30
    assert base.stock_lotes.find_one({"_id": "L900"})["vencimiento"] == datetime(2026, 12, 20)
    # Los originales no se tocan.
    assert base.stock_lotes.find_one({"_id": "L001"})["vencimiento"] == datetime(2027, 8, 31)

    cargar(hoy=date(2026, 12, 13), dir_adicionales=tmp_path, desplazar=False)
    assert base.stock_lotes.find_one({"_id": "L900"})["vencimiento"] == datetime(2026, 11, 20)
