"""Carga de datos: de los CSV al estado inicial de MongoDB y Redis.

Pasos de `cargar()`:
1. Lee `data/original` (obligatorio) y `data/extra` (registros adicionales, opcional).
2. Desplaza las fechas de los registros adicionales (ver más abajo).
3. Valida todo en memoria; ante cualquier error no escribe nada.
4. Recrea las colecciones (validadores + índices), inserta los documentos y fija los contadores.
5. Reconstruye las vistas de Redis.

Es idempotente porque siempre reconstruye el mismo estado inicial: ejecutarla dos veces deja
exactamente lo mismo que ejecutarla una. Por eso mismo BORRA lo que hayan creado los servicios
(ventas nuevas, descuentos de stock, altas de clientes).

Desplazamiento de fechas: las consultas usan la fecha del sistema ("mes actual", "últimos 60
días"), así que un registro adicional con fecha fija deja de ser "reciente" con el paso de las
semanas. Los CSV adicionales se escriben con fechas ISO normales tomando como "hoy" la fecha de
`data/extra/FECHA_REFERENCIA`; al cargar, a cada fecha se le suma (hoy - referencia). Los CSV
originales de la cátedra nunca se modifican.
"""

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from farmared import config, vistas
from farmared.carga.lector import ENTIDADES, leer_directorio
from farmared.carga.validacion import validar
from farmared.db import get_mongo_db
from farmared.errores import ErrorCarga
from farmared.esquema import crear_esquema
from farmared.fechas import a_datetime, resolver_hoy
from farmared.ids import inicializar_contadores, numero_de

ARCHIVO_REFERENCIA = "FECHA_REFERENCIA"


def leer_fecha_referencia(directorio: Path) -> date:
    """Fecha que los registros adicionales toman como "hoy" (primera línea que no es comentario)."""
    ruta = directorio / ARCHIVO_REFERENCIA
    if not ruta.exists():
        raise ErrorCarga([f"falta {ruta}: hace falta para desplazar las fechas adicionales"])
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#"):
            try:
                return date.fromisoformat(linea)
            except ValueError:
                raise ErrorCarga([f"{ruta}: {linea!r} no es una fecha AAAA-MM-DD"]) from None
    raise ErrorCarga([f"{ruta}: no contiene ninguna fecha"])


def desplazar_fechas(datos: dict[str, list[dict]], delta: timedelta) -> None:
    """Suma `delta` a todas las fechas de `datos` (modifica las filas)."""
    for filas in datos.values():
        for fila in filas:
            for campo, valor in fila.items():
                if isinstance(valor, date):
                    fila[campo] = valor + delta


def construir_documentos(datos: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Transforma las filas de los CSV en los documentos del modelo (ver `esquema.py`)."""
    sucursal_de = {f["id_farmaceutico"]: f["id_sucursal"] for f in datos["farmaceuticos"]}

    items_por_venta: dict[str, list[dict]] = defaultdict(list)
    for d in sorted(datos["detalle_ventas"], key=lambda d: d["id_detalle"]):
        items_por_venta[d["id_venta"]].append({
            "id_detalle": d["id_detalle"],
            "id_producto": d["id_producto"],
            "cantidad": d["cantidad"],
            "precio_unit": d["precio_unit"],
        })

    return {
        "clientes": [{
            "_id": c["id_cliente"],
            "nombre": c["nombre"],
            "apellido": c["apellido"],
            "dni": c["dni"],
            "contacto": {"email": c["email"], "telefono": c["telefono"]},
            "domicilio": {"ciudad": c["ciudad"], "provincia": c["provincia"]},
            "cobertura": {"obra_social": c["obra_social"], "nro_afiliado": c["nro_afiliado"]},
            "activo": c["activo"],
        } for c in datos["clientes"]],
        "sucursales": [_con_id(s, "id_sucursal") for s in datos["sucursales"]],
        "farmaceuticos": [_con_id(f, "id_farmaceutico") for f in datos["farmaceuticos"]],
        "proveedores": [_con_id(p, "id_proveedor") for p in datos["proveedores"]],
        "productos": [_con_id(p, "id_producto") for p in datos["productos"]],
        "stock_lotes": [{
            **_con_id(lote, "id_lote"),
            "vencimiento": a_datetime(lote["vencimiento"]),
        } for lote in datos["stock_lotes"]],
        "recetas": [{
            "_id": r["id_receta"],
            "id_cliente": r["id_cliente"],
            "medico": {"nombre": r["medico"], "matricula": r["matricula_medico"]},
            "fecha_emision": a_datetime(r["fecha_emision"]),
            "tipo": r["tipo"],
            "dispensas_autorizadas": r["dispensas_autorizadas"],
            "dispensas_realizadas": r["dispensas_realizadas"],
            "proxima_dispensa": a_datetime(r["proxima_dispensa"]),
            "estado": r["estado"],
        } for r in datos["recetas"]],
        "ventas": [{
            "_id": v["id_venta"],
            "id_cliente": v["id_cliente"],
            "id_farmaceutico": v["id_farmaceutico"],
            "id_sucursal": sucursal_de[v["id_farmaceutico"]],
            "id_receta": v["id_receta"],
            "fecha": a_datetime(v["fecha"]),
            "tipo": v["tipo"],
            "medio_pago": v["medio_pago"],
            "total": v["total"],
            "estado": v["estado"],
            "items": items_por_venta[v["id_venta"]],
            # stock_lotes.csv ya es la foto actual del stock: las ventas completadas del
            # historial figuran como ya descontadas y no se vuelven a aplicar.
            "stock_aplicado": v["estado"] == "Completada",
            "lotes_consumidos": [],
        } for v in datos["ventas"]],
    }


def _con_id(fila: dict, campo_id: str) -> dict:
    """Copia de la fila con el id de negocio como `_id`."""
    documento = {"_id": fila[campo_id]}
    documento.update((campo, valor) for campo, valor in fila.items() if campo != campo_id)
    return documento


def cargar(
    hoy: date | None = None,
    desplazar: bool = True,
    dir_originales: Path | None = None,
    dir_adicionales: Path | None = None,
) -> dict:
    """Lleva MongoDB y Redis al estado inicial definido por los CSV.

    Parámetros:
        hoy: fecha contra la que se desplazan los adicionales (por defecto, la del sistema).
        desplazar: False carga las fechas adicionales tal cual están escritas.
        dir_originales / dir_adicionales: carpetas de los CSV (por defecto, las de `config`).
    Retorna: resumen con documentos por colección, filas adicionales, días desplazados y vistas.
    Lanza `ErrorCarga` si los datos no son válidos (sin haber escrito nada).
    """
    hoy = resolver_hoy(hoy)
    dir_originales = dir_originales or config.DIR_ORIGINALES
    dir_adicionales = dir_adicionales or config.DIR_ADICIONALES

    datos = leer_directorio(dir_originales, obligatorio=True)
    adicionales = leer_directorio(dir_adicionales, obligatorio=False)
    cantidad_adicionales = sum(len(filas) for filas in adicionales.values())

    dias = None
    if cantidad_adicionales and desplazar:
        delta = hoy - leer_fecha_referencia(dir_adicionales)
        desplazar_fechas(adicionales, delta)
        dias = delta.days

    for entidad in ENTIDADES:
        datos[entidad] += adicionales[entidad]

    errores = validar(datos)
    if errores:
        raise ErrorCarga(errores)

    documentos = construir_documentos(datos)
    db = get_mongo_db()
    crear_esquema(db)
    for coleccion, docs in documentos.items():
        if docs:
            db[coleccion].insert_many(docs)
    inicializar_contadores(db, {
        "clientes": _mayor_numero(datos["clientes"], "id_cliente"),
        "ventas": _mayor_numero(datos["ventas"], "id_venta"),
        "detalles": _mayor_numero(datos["detalle_ventas"], "id_detalle"),
    })

    return {
        "colecciones": {coleccion: len(docs) for coleccion, docs in documentos.items()},
        "filas_adicionales": cantidad_adicionales,
        "dias_desplazados": dias,
        "vistas_redis": vistas.reconstruir(),
    }


def _mayor_numero(filas: list[dict], campo_id: str) -> int:
    return max((numero_de(f[campo_id]) for f in filas), default=0)
