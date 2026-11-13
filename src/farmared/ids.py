"""Generación de identificadores nuevos (C009, V017, D023, ...).

Cada entidad con altas tiene un documento en la colección `contadores`. Reservar ids es un
`$inc` atómico, así dos operaciones simultáneas nunca reciben el mismo id.

La reserva se hace fuera de las transacciones a propósito: si se hiciera dentro, todas las
ventas simultáneas chocarían por escribir el mismo contador. El costo es que una operación
rechazada puede dejar un número sin usar, lo cual no afecta a nada.
"""

import re

from pymongo import ReturnDocument
from pymongo.database import Database

from farmared.errores import ErrorFarmaRed

# entidad -> (prefijo, cantidad mínima de dígitos)
CONTADORES: dict[str, tuple[str, int]] = {
    "clientes": ("C", 3),
    "ventas": ("V", 3),
    "detalles": ("D", 3),
}


def numero_de(identificador: str) -> int:
    """Parte numérica final de un id: 'V016' -> 16."""
    return int(re.search(r"(\d+)$", identificador).group(1))


def inicializar_contadores(db: Database, ultimos: dict[str, int]) -> None:
    """Fija cada contador en el mayor número ya usado por los datos cargados."""
    db.contadores.insert_many([
        {"_id": entidad, "prefijo": prefijo, "ancho": ancho, "seq": ultimos.get(entidad, 0)}
        for entidad, (prefijo, ancho) in CONTADORES.items()
    ])


def reservar_ids(db: Database, entidad: str, cantidad: int = 1) -> list[str]:
    """Reserva `cantidad` ids consecutivos de `entidad` y los devuelve en orden."""
    doc = db.contadores.find_one_and_update(
        {"_id": entidad},
        {"$inc": {"seq": cantidad}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise ErrorFarmaRed(f"no existe el contador '{entidad}': ejecutar primero `make cargar`")
    ultimo = doc["seq"]
    return [
        f"{doc['prefijo']}{n:0{doc['ancho']}d}"
        for n in range(ultimo - cantidad + 1, ultimo + 1)
    ]
