"""Tests de q13 (ABM de clientes): alta, modificación de contacto y cobertura, y baja lógica.

Parten de los CSV originales (fixture `base`): 8 clientes, así que el próximo id es C009.
C001 tiene DNI 31245678 y OSDE; C005 es 'Sin cobertura'; C008 está dado de baja (DNI 25678901).
"""

from threading import Thread

import pytest
from conftest import HOY

from farmared.consultas.q13_abm_clientes import alta_cliente, baja_cliente, modificar_cliente
from farmared.consultas.q14_registrar_venta import registrar_venta
from farmared.errores import ErrorValidacion

DATOS_ALTA = {
    "nombre": "Ana", "apellido": "Paz", "dni": "40111222", "email": "ana.p@gmail.com",
    "telefono": "3415001122", "ciudad": "Rosario", "provincia": "Santa Fe",
    "obra_social": "OSDE", "nro_afiliado": "OS-777001",
}


def clientes(db) -> list[dict]:
    return list(db.clientes.find().sort("_id", 1))


# --- Alta ---------------------------------------------------------------------------------------

def test_alta_crea_cliente_activo_con_id_nuevo(base):
    resultado = alta_cliente(**DATOS_ALTA)

    assert resultado["antes"] is None
    esperado = {
        "_id": "C009", "nombre": "Ana", "apellido": "Paz", "dni": "40111222",
        "contacto": {"email": "ana.p@gmail.com", "telefono": "3415001122"},
        "domicilio": {"ciudad": "Rosario", "provincia": "Santa Fe"},
        "cobertura": {"obra_social": "OSDE", "nro_afiliado": "OS-777001"},
        "activo": True,
    }
    assert resultado["despues"] == esperado
    assert base.clientes.find_one({"_id": "C009"}) == esperado
    assert base.clientes.count_documents({}) == 9


def test_alta_sin_cobertura_y_ids_consecutivos(base):
    alta_cliente(**{**DATOS_ALTA, "obra_social": "Sin cobertura", "nro_afiliado": None})
    segundo = alta_cliente(**{**DATOS_ALTA, "dni": "40111223"})

    assert base.clientes.find_one({"_id": "C009"})["cobertura"] == {
        "obra_social": "Sin cobertura", "nro_afiliado": None,
    }
    assert segundo["despues"]["_id"] == "C010"


def test_alta_normaliza_espacios(base):
    resultado = alta_cliente(**{**DATOS_ALTA, "nombre": "  Ana ", "dni": " 40111222 "})
    assert (resultado["despues"]["nombre"], resultado["despues"]["dni"]) == ("Ana", "40111222")


@pytest.mark.parametrize("dni, motivo", [
    ("31245678", "cliente C001"),             # DNI de un cliente activo
    ("25678901", "C008, dado de baja"),      # el DNI de un cliente dado de baja tampoco se reutiliza
])
def test_alta_rechaza_dni_duplicado(base, dni, motivo):
    antes = clientes(base)
    with pytest.raises(ErrorValidacion, match=f"ya existe un cliente con DNI {dni}.*{motivo}"):
        alta_cliente(**{**DATOS_ALTA, "dni": dni})
    assert clientes(base) == antes


def test_dos_altas_simultaneas_con_el_mismo_dni(base):
    resultados = []

    def alta():
        try:
            alta_cliente(**DATOS_ALTA)
            resultados.append("ok")
        except ErrorValidacion:
            resultados.append("rechazada")

    hilos = [Thread(target=alta) for _ in range(2)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert sorted(resultados) == ["ok", "rechazada"]
    assert base.clientes.count_documents({"dni": "40111222"}) == 1


@pytest.mark.parametrize("cambios, motivo", [
    ({"nombre": "  "}, "nombre es obligatorio"),
    ({"email": None}, "email es obligatorio"),
    ({"email": "ana.gmail.com"}, "email"),
    ({"dni": "31.245.678"}, "7 u 8 dígitos"),
    ({"dni": "123"}, "7 u 8 dígitos"),
    ({"obra_social": "Medifé"}, "obra social 'Medifé' inválida"),
    ({"nro_afiliado": None}, "falta el número de afiliado"),
    ({"obra_social": "Sin cobertura"}, "no tiene número de afiliado"),
])
def test_alta_rechaza_datos_invalidos(base, cambios, motivo):
    antes = clientes(base)
    with pytest.raises(ErrorValidacion, match=motivo):
        alta_cliente(**{**DATOS_ALTA, **cambios})
    assert clientes(base) == antes


# --- Modificación ---------------------------------------------------------------------------------

def test_modificar_contacto(base):
    resultado = modificar_cliente("C001", email="lucia.nueva@gmail.com", telefono="1140001111")

    assert resultado["antes"]["contacto"] == {"email": "lucia.f@gmail.com", "telefono": "1145112233"}
    despues = base.clientes.find_one({"_id": "C001"})
    assert resultado["despues"] == despues
    assert despues["contacto"] == {"email": "lucia.nueva@gmail.com", "telefono": "1140001111"}
    # Lo demás no cambia.
    assert {k: v for k, v in despues.items() if k != "contacto"} == {
        k: v for k, v in resultado["antes"].items() if k != "contacto"
    }


def test_modificar_solo_telefono_conserva_email(base):
    modificar_cliente("C001", telefono="1140001111")
    assert base.clientes.find_one({"_id": "C001"})["contacto"] == {
        "email": "lucia.f@gmail.com", "telefono": "1140001111",
    }


def test_modificar_cobertura_a_otra_obra_social(base):
    modificar_cliente("C001", obra_social="PAMI", nro_afiliado="PA-100200")
    assert base.clientes.find_one({"_id": "C001"})["cobertura"] == {
        "obra_social": "PAMI", "nro_afiliado": "PA-100200",
    }


def test_modificar_a_sin_cobertura_vacia_el_afiliado(base):
    modificar_cliente("C001", obra_social="Sin cobertura")
    assert base.clientes.find_one({"_id": "C001"})["cobertura"] == {
        "obra_social": "Sin cobertura", "nro_afiliado": None,
    }


def test_modificar_de_sin_cobertura_a_con_cobertura(base):
    modificar_cliente("C005", obra_social="Galeno", nro_afiliado="GA-300400")
    assert base.clientes.find_one({"_id": "C005"})["cobertura"] == {
        "obra_social": "Galeno", "nro_afiliado": "GA-300400",
    }


def test_modificar_solo_el_numero_de_afiliado(base):
    modificar_cliente("C001", nro_afiliado="OS-999999")
    assert base.clientes.find_one({"_id": "C001"})["cobertura"] == {
        "obra_social": "OSDE", "nro_afiliado": "OS-999999",
    }


@pytest.mark.parametrize("id_cliente, cambios, motivo", [
    ("C001", {}, "no hay datos para modificar"),
    ("C999", {"email": "x@gmail.com"}, "C999 no existe"),
    ("C008", {"email": "x@gmail.com"}, "dado de baja"),
    ("C001", {"email": "sin-arroba"}, "email"),
    ("C001", {"telefono": " "}, "telefono es obligatorio"),
    ("C001", {"obra_social": "PAMI"}, "falta el número de afiliado de PAMI"),
    ("C001", {"obra_social": "Sin cobertura", "nro_afiliado": "X-1"}, "no tiene número de afiliado"),
    ("C005", {"nro_afiliado": "X-1"}, "no tiene número de afiliado"),  # es 'Sin cobertura'
    ("C001", {"obra_social": "Medifé", "nro_afiliado": "M-1"}, "inválida"),
])
def test_modificar_rechaza_sin_cambiar_nada(base, id_cliente, cambios, motivo):
    antes = clientes(base)
    with pytest.raises(ErrorValidacion, match=motivo):
        modificar_cliente(id_cliente, **cambios)
    assert clientes(base) == antes


# --- Baja lógica ----------------------------------------------------------------------------------

def test_baja_logica_conserva_el_documento(base):
    resultado = baja_cliente("C004")

    assert resultado["antes"]["activo"] is True
    despues = base.clientes.find_one({"_id": "C004"})
    assert resultado["despues"] == despues
    assert despues == {**resultado["antes"], "activo": False}  # solo cambia `activo`
    assert base.clientes.count_documents({}) == 8  # no se borró nada
    assert base.recetas.count_documents({"id_cliente": "C004"}) > 0  # sus referencias siguen


@pytest.mark.parametrize("id_cliente, motivo", [
    ("C008", "está dado de baja"),
    ("C999", "no existe"),
])
def test_baja_rechazada(base, id_cliente, motivo):
    antes = clientes(base)
    with pytest.raises(ErrorValidacion, match=motivo):
        baja_cliente(id_cliente)
    assert clientes(base) == antes


def test_cliente_dado_de_baja_no_puede_comprar(base):
    baja_cliente("C005")
    with pytest.raises(ErrorValidacion, match="dado de baja"):
        registrar_venta("C005", "F005", [{"id_producto": "PRD001", "cantidad": 1}], "Efectivo", hoy=HOY)
