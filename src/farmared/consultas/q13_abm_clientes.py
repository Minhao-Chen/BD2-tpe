"""q13 — ABM de clientes: alta, modificación de contacto y cobertura, y baja lógica.

Propósito:
    Administrar los clientes de la red respetando las reglas del modelo:
    - alta: crea un cliente activo con un id nuevo (C019, C020, ...), validando que el DNI no
      esté registrado (tampoco en un cliente dado de baja: el documento sigue existiendo);
    - modificación: cambia los datos de contacto (email, teléfono) y/o la cobertura (obra social
      y número de afiliado) de un cliente activo;
    - baja: baja lógica (activo = False). El cliente no se borra: sus ventas y recetas lo siguen
      referenciando y q03, q10 y q12 lo siguen mostrando; q14 ya no le registra ventas.

Funciones y parámetros:
    alta_cliente(nombre, apellido, dni, email, telefono, ciudad, provincia, obra_social,
                 nro_afiliado=None)
        Todos los textos son obligatorios salvo nro_afiliado. dni: 7 u 8 dígitos.
    modificar_cliente(id_cliente, email=None, telefono=None, obra_social=None,
                      nro_afiliado=None)
        Solo se modifican los campos que se pasan (al menos uno).
    baja_cliente(id_cliente)

Validaciones (cualquiera que falle rechaza la operación con ErrorValidacion, sin escribir):
    - textos no vacíos; email con '@'; dni numérico de 7 u 8 dígitos;
    - obra_social es una de OSDE, Swiss Medical, PAMI, IOMA, Galeno o 'Sin cobertura';
    - cobertura coherente: nro_afiliado vacío si y solo si es 'Sin cobertura'. Al modificar,
      si se pasa obra_social se pasa también su nro_afiliado (salvo 'Sin cobertura', que lo
      deja vacío); si solo se pasa nro_afiliado, el cliente debe tener obra social;
    - alta: DNI no registrado;
    - modificación y baja: el cliente existe y está activo.

Retorno:
    {"antes": documento previo (None en el alta), "despues": documento resultante}
    Así cada operación muestra el estado antes y después.

Motor:
    MongoDB, colección `clientes`. Cada operación escribe un único documento, y en MongoDB
    la escritura de un documento es atómica: no hace falta transacción.
    - Unicidad del DNI: se consulta antes de insertar (para dar un mensaje claro) y además la
      garantiza el índice único {dni}. Si dos altas con el mismo DNI llegan a la vez, la segunda
      choca contra el índice (DuplicateKeyError) y se rechaza igual.
    - El id sale del contador atómico `contadores.clientes` (ver ids.py).
    - Modificación y baja usan `find_one_and_update` con filtro {_id, activo: True}: si otra
      operación dio de baja al cliente entre la lectura y la escritura, no se modifica nada.
    - El validador $jsonSchema de la colección es la última barrera (campos y enum).

Uso:
    make consulta Q=q13 ARGS="alta --nombre Ana --apellido Paz --dni 40111222 --email ana@mail.com --telefono 1144556677 --ciudad Rosario --provincia 'Santa Fe' --obra-social OSDE --nro-afiliado OS-1234"
    make consulta Q=q13 ARGS="modificar C001 --email nuevo@mail.com --obra-social PAMI --nro-afiliado PA-1"
    make consulta Q=q13 ARGS="baja C004"
"""

import argparse
import re

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from farmared.db import get_mongo_db
from farmared.errores import ErrorValidacion
from farmared.esquema import OBRAS_SOCIALES, SIN_COBERTURA
from farmared.ids import reservar_ids

_PATRON_DNI = re.compile(r"^\d{7,8}$")


# --- Validaciones ------------------------------------------------------------------------------

def _texto(campo: str, valor) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorValidacion(f"el campo {campo} es obligatorio")
    return valor.strip()


def _texto_opcional(campo: str, valor) -> str | None:
    """None o texto vacío -> None; si no, el texto sin espacios de más."""
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise ErrorValidacion(f"el campo {campo} debe ser texto")
    return valor.strip() or None


def _dni(valor) -> str:
    dni = _texto("dni", valor)
    if not _PATRON_DNI.match(dni):
        raise ErrorValidacion(f"dni {dni!r} inválido: se esperan 7 u 8 dígitos, sin puntos")
    return dni


def _email(valor) -> str:
    email = _texto("email", valor)
    if "@" not in email:
        raise ErrorValidacion(f"email {email!r} inválido")
    return email


def _cobertura(obra_social, nro_afiliado) -> dict:
    """Valida y devuelve {obra_social, nro_afiliado} coherentes entre sí."""
    obra_social = _texto("obra_social", obra_social)
    if obra_social not in OBRAS_SOCIALES:
        raise ErrorValidacion(
            f"obra social {obra_social!r} inválida; opciones: {', '.join(OBRAS_SOCIALES)}"
        )
    nro_afiliado = _texto_opcional("nro_afiliado", nro_afiliado)
    if obra_social == SIN_COBERTURA and nro_afiliado is not None:
        raise ErrorValidacion("un cliente 'Sin cobertura' no tiene número de afiliado")
    if obra_social != SIN_COBERTURA and nro_afiliado is None:
        raise ErrorValidacion(f"falta el número de afiliado de {obra_social}")
    return {"obra_social": obra_social, "nro_afiliado": nro_afiliado}


def _cliente_activo(db, id_cliente: str) -> dict:
    cliente = db.clientes.find_one({"_id": id_cliente})
    if cliente is None:
        raise ErrorValidacion(f"el cliente {id_cliente} no existe")
    if not cliente["activo"]:
        raise ErrorValidacion(f"el cliente {id_cliente} está dado de baja")
    return cliente


def _rechazo_dni(db, dni: str) -> ErrorValidacion:
    existente = db.clientes.find_one({"dni": dni}, {"_id": 1, "activo": 1})
    detalle = ""
    if existente is not None:
        detalle = f" (cliente {existente['_id']}{'' if existente['activo'] else ', dado de baja'})"
    return ErrorValidacion(f"ya existe un cliente con DNI {dni}{detalle}")


# --- Servicios ---------------------------------------------------------------------------------

def alta_cliente(
    nombre: str,
    apellido: str,
    dni: str,
    email: str,
    telefono: str,
    ciudad: str,
    provincia: str,
    obra_social: str,
    nro_afiliado: str | None = None,
) -> dict:
    cliente = {
        "nombre": _texto("nombre", nombre),
        "apellido": _texto("apellido", apellido),
        "dni": _dni(dni),
        "contacto": {"email": _email(email), "telefono": _texto("telefono", telefono)},
        "domicilio": {"ciudad": _texto("ciudad", ciudad), "provincia": _texto("provincia", provincia)},
        "cobertura": _cobertura(obra_social, nro_afiliado),
        "activo": True,
    }

    db = get_mongo_db()
    if db.clientes.find_one({"dni": cliente["dni"]}, {"_id": 1}) is not None:
        raise _rechazo_dni(db, cliente["dni"])

    cliente = {"_id": reservar_ids(db, "clientes")[0], **cliente}
    try:
        db.clientes.insert_one(cliente)
    except DuplicateKeyError:
        # Otra alta con el mismo DNI se insertó entre la consulta y el insert.
        raise _rechazo_dni(db, cliente["dni"]) from None
    return {"antes": None, "despues": db.clientes.find_one({"_id": cliente["_id"]})}


def modificar_cliente(
    id_cliente: str,
    email: str | None = None,
    telefono: str | None = None,
    obra_social: str | None = None,
    nro_afiliado: str | None = None,
) -> dict:
    if all(v is None for v in (email, telefono, obra_social, nro_afiliado)):
        raise ErrorValidacion(
            "no hay datos para modificar: indicar email, telefono, obra_social o nro_afiliado"
        )

    db = get_mongo_db()
    antes = _cliente_activo(db, id_cliente)

    cambios: dict = {}
    if email is not None:
        cambios["contacto.email"] = _email(email)
    if telefono is not None:
        cambios["contacto.telefono"] = _texto("telefono", telefono)
    if obra_social is not None:
        cobertura = _cobertura(obra_social, nro_afiliado)
    elif nro_afiliado is not None:
        # Solo cambia el número: se conserva la obra social actual.
        cobertura = _cobertura(antes["cobertura"]["obra_social"], nro_afiliado)
    else:
        cobertura = None
    if cobertura is not None:
        cambios["cobertura"] = cobertura

    despues = db.clientes.find_one_and_update(
        {"_id": id_cliente, "activo": True},
        {"$set": cambios},
        return_document=ReturnDocument.AFTER,
    )
    if despues is None:
        raise ErrorValidacion(f"el cliente {id_cliente} fue dado de baja por otra operación")
    return {"antes": antes, "despues": despues}


def baja_cliente(id_cliente: str) -> dict:
    db = get_mongo_db()
    antes = _cliente_activo(db, id_cliente)
    despues = db.clientes.find_one_and_update(
        {"_id": id_cliente, "activo": True},
        {"$set": {"activo": False}},
        return_document=ReturnDocument.AFTER,
    )
    if despues is None:
        raise ErrorValidacion(f"el cliente {id_cliente} ya fue dado de baja por otra operación")
    return {"antes": antes, "despues": despues}


# --- CLI -----------------------------------------------------------------------------------------

def cli(argv: list[str]) -> dict:
    parser = argparse.ArgumentParser(prog="q13", description="ABM de clientes.")
    sub = parser.add_subparsers(dest="operacion", required=True)

    alta = sub.add_parser("alta", help="da de alta un cliente")
    for campo in ("nombre", "apellido", "dni", "email", "telefono", "ciudad", "provincia"):
        alta.add_argument(f"--{campo}", required=True)
    alta.add_argument("--obra-social", required=True, choices=OBRAS_SOCIALES)
    alta.add_argument("--nro-afiliado", default=None, help="vacío si es 'Sin cobertura'")

    modificar = sub.add_parser("modificar", help="modifica contacto y/o cobertura")
    modificar.add_argument("id_cliente")
    modificar.add_argument("--email")
    modificar.add_argument("--telefono")
    modificar.add_argument("--obra-social", choices=OBRAS_SOCIALES)
    modificar.add_argument("--nro-afiliado")

    baja = sub.add_parser("baja", help="baja lógica (activo = False)")
    baja.add_argument("id_cliente")

    args = parser.parse_args(argv)
    if args.operacion == "alta":
        return alta_cliente(
            args.nombre, args.apellido, args.dni, args.email, args.telefono,
            args.ciudad, args.provincia, args.obra_social, args.nro_afiliado,
        )
    if args.operacion == "modificar":
        return modificar_cliente(
            args.id_cliente, args.email, args.telefono, args.obra_social, args.nro_afiliado,
        )
    return baja_cliente(args.id_cliente)
