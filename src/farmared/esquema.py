"""Modelo de datos en MongoDB: colecciones, validadores `$jsonSchema` e índices.

Convenciones:
- `_id` es el identificador de negocio del CSV (C001, V001, ...): unicidad garantizada por Mongo.
- Las relaciones N:1 se guardan como referencia (`id_...`) y se resuelven con `$lookup`.
- El detalle de cada venta va embebido en `ventas.items` (siempre se lee y escribe con la venta).
- Los campos que pueden faltar se guardan igual, con valor `null`.
- Las fechas son Date (medianoche UTC del día de negocio).

Los validadores son la última barrera de integridad: enums, campos obligatorios y rangos
(por ejemplo `unidades >= 0`, que impide stock negativo aunque falle la aplicación).
"""

from pymongo.database import Database

# --- Valores permitidos (enunciado, sección 2) --------------------------------------------
OBRAS_SOCIALES = ["OSDE", "Swiss Medical", "PAMI", "IOMA", "Galeno", "Sin cobertura"]
SIN_COBERTURA = "Sin cobertura"
TIPOS_SUCURSAL = ["Farmacia", "Droguería"]
CARGOS = ["Director Técnico", "Farmacéutico"]
TIPOS_PROVEEDOR = ["Laboratorio", "Droguería"]
CONDICIONES_VENTA = ["Venta libre", "Bajo receta", "Bajo receta archivada"]
VENTA_LIBRE = "Venta libre"
TIPOS_RECETA = ["Simple", "Archivada", "Tratamiento prolongado"]
TRATAMIENTO_PROLONGADO = "Tratamiento prolongado"
ESTADOS_RECETA = ["Vigente", "Completada", "Vencida"]
TIPOS_VENTA = ["Venta libre", "Con receta"]
MEDIOS_PAGO = ["Efectivo", "Débito", "Crédito", "Transferencia", "Obra social"]
ESTADOS_VENTA = ["Completada", "Pendiente", "Anulada"]

# --- Piezas de esquema ---------------------------------------------------------------------
_TEXTO = {"bsonType": "string", "minLength": 1}
_TEXTO_O_NULO = {"bsonType": ["string", "null"]}
_BOOL = {"bsonType": "bool"}
_FECHA = {"bsonType": "date"}
_FECHA_O_NULA = {"bsonType": ["date", "null"]}


def _entero(minimo: int) -> dict:
    return {"bsonType": ["int", "long"], "minimum": minimo}


def _enum(valores: list[str]) -> dict:
    return {"enum": valores}


def _objeto(propiedades: dict) -> dict:
    """Objeto con todas sus propiedades obligatorias."""
    return {"bsonType": "object", "required": list(propiedades), "properties": propiedades}


def _lista(elemento: dict, minimo: int = 0) -> dict:
    return {"bsonType": "array", "minItems": minimo, "items": elemento}


ESQUEMAS: dict[str, dict] = {
    "clientes": _objeto({
        "_id": _TEXTO,
        "nombre": _TEXTO,
        "apellido": _TEXTO,
        "dni": _TEXTO,
        "contacto": _objeto({"email": _TEXTO, "telefono": _TEXTO}),
        "domicilio": _objeto({"ciudad": _TEXTO, "provincia": _TEXTO}),
        "cobertura": _objeto({
            "obra_social": _enum(OBRAS_SOCIALES),
            "nro_afiliado": _TEXTO_O_NULO,
        }),
        "activo": _BOOL,
    }),
    "sucursales": _objeto({
        "_id": _TEXTO,
        "nombre": _TEXTO,
        "tipo": _enum(TIPOS_SUCURSAL),
        "direccion": _TEXTO,
        "ciudad": _TEXTO,
        "provincia": _TEXTO,
        "telefono": _TEXTO,
        "activo": _BOOL,
    }),
    "farmaceuticos": _objeto({
        "_id": _TEXTO,
        "nombre": _TEXTO,
        "apellido": _TEXTO,
        "matricula": _TEXTO,
        "cargo": _enum(CARGOS),
        "id_sucursal": _TEXTO,
        "activo": _BOOL,
    }),
    "proveedores": _objeto({
        "_id": _TEXTO,
        "razon_social": _TEXTO,
        "cuit": _TEXTO,
        "tipo": _enum(TIPOS_PROVEEDOR),
        "ciudad": _TEXTO,
        "provincia": _TEXTO,
        "telefono": _TEXTO,
        "activo": _BOOL,
    }),
    "productos": _objeto({
        "_id": _TEXTO,
        "nombre": _TEXTO,
        "principio_activo": _TEXTO,
        "categoria": _TEXTO,
        "presentacion": _TEXTO,
        "condicion_venta": _enum(CONDICIONES_VENTA),
        "precio_unit": _entero(1),
        "id_proveedor": _TEXTO,
        "activo": _BOOL,
    }),
    "stock_lotes": _objeto({
        "_id": _TEXTO,
        "id_producto": _TEXTO,
        "id_sucursal": _TEXTO,
        "nro_lote": _TEXTO,
        "unidades": _entero(0),
        "vencimiento": _FECHA,
    }),
    "recetas": _objeto({
        "_id": _TEXTO,
        "id_cliente": _TEXTO,
        "medico": _objeto({"nombre": _TEXTO, "matricula": _TEXTO}),
        "fecha_emision": _FECHA,
        "tipo": _enum(TIPOS_RECETA),
        "dispensas_autorizadas": _entero(1),
        "dispensas_realizadas": _entero(0),
        "proxima_dispensa": _FECHA_O_NULA,
        "estado": _enum(ESTADOS_RECETA),
    }),
    "ventas": _objeto({
        "_id": _TEXTO,
        "id_cliente": _TEXTO,
        "id_farmaceutico": _TEXTO,
        # Sucursal del farmacéutico al momento de la venta (dato fijo de la venta).
        "id_sucursal": _TEXTO,
        "id_receta": _TEXTO_O_NULO,
        "fecha": _FECHA,
        "tipo": _enum(TIPOS_VENTA),
        "medio_pago": _enum(MEDIOS_PAGO),
        "total": _entero(0),
        "estado": _enum(ESTADOS_VENTA),
        "items": _lista(_objeto({
            "id_detalle": _TEXTO,
            "id_producto": _TEXTO,
            "cantidad": _entero(1),
            "precio_unit": _entero(1),
        }), minimo=1),
        # True cuando el stock de esta venta ya fue descontado (q15 no lo repite).
        "stock_aplicado": _BOOL,
        "lotes_consumidos": _lista(_objeto({
            "id_lote": _TEXTO,
            "id_producto": _TEXTO,
            "unidades": _entero(1),
        })),
    }),
    "contadores": _objeto({
        "_id": _TEXTO,
        "prefijo": _TEXTO,
        "ancho": _entero(1),
        "seq": _entero(0),
    }),
}

# (claves, opciones) por colección. El índice de `_id` ya existe siempre.
INDICES: dict[str, list[tuple[list[tuple[str, int]], dict]]] = {
    "clientes": [([("dni", 1)], {"unique": True})],
    "farmaceuticos": [
        ([("matricula", 1)], {"unique": True}),
        ([("id_sucursal", 1)], {}),
    ],
    "proveedores": [([("cuit", 1)], {"unique": True})],
    "productos": [([("id_proveedor", 1)], {})],
    "stock_lotes": [
        # FEFO: lotes de un producto en una sucursal, del vencimiento más próximo al más lejano.
        ([("id_sucursal", 1), ("id_producto", 1), ("vencimiento", 1)], {}),
        ([("unidades", 1)], {}),
    ],
    "recetas": [
        ([("id_cliente", 1)], {}),
        ([("tipo", 1), ("estado", 1), ("proxima_dispensa", 1)], {}),
    ],
    "ventas": [
        ([("id_cliente", 1), ("fecha", 1)], {}),
        ([("id_farmaceutico", 1), ("fecha", 1)], {}),
        ([("id_sucursal", 1)], {}),
        ([("estado", 1), ("fecha", 1)], {}),
    ],
}

COLECCIONES: list[str] = list(ESQUEMAS)


def crear_esquema(db: Database) -> None:
    """Borra y vuelve a crear todas las colecciones, con sus validadores e índices."""
    for nombre in COLECCIONES:
        db.drop_collection(nombre)
        db.create_collection(nombre, validator={"$jsonSchema": ESQUEMAS[nombre]})
        for claves, opciones in INDICES.get(nombre, []):
            db[nombre].create_index(claves, **opciones)
