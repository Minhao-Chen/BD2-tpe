"""Validación de los datos antes de escribir nada en las bases.

MongoDB no verifica integridad referencial, así que la carga lo hace acá, en memoria:
si algo falla, se informa la lista completa de errores y no se escribe ningún documento.

Dos etapas:
1. Estructura: formato y unicidad de ids, campos obligatorios, valores permitidos, claves únicas
   de negocio y referencias entre archivos.
2. Reglas de negocio (solo si la estructura está bien): coherencia de coberturas, recetas,
   totales de ventas, etc.
"""

import re
from collections import Counter, defaultdict

from farmared import esquema

# entidad -> (campo id, prefijo)
IDS: dict[str, tuple[str, str]] = {
    "clientes": ("id_cliente", "C"),
    "sucursales": ("id_sucursal", "S"),
    "farmaceuticos": ("id_farmaceutico", "F"),
    "proveedores": ("id_proveedor", "PRV"),
    "productos": ("id_producto", "PRD"),
    "stock_lotes": ("id_lote", "L"),
    "recetas": ("id_receta", "RC"),
    "ventas": ("id_venta", "V"),
    "detalle_ventas": ("id_detalle", "D"),
}

# Únicos campos que pueden venir vacíos.
NULABLES = {
    ("clientes", "nro_afiliado"),
    ("recetas", "proxima_dispensa"),
    ("ventas", "id_receta"),
}

ENUMS: dict[tuple[str, str], list[str]] = {
    ("clientes", "obra_social"): esquema.OBRAS_SOCIALES,
    ("sucursales", "tipo"): esquema.TIPOS_SUCURSAL,
    ("farmaceuticos", "cargo"): esquema.CARGOS,
    ("proveedores", "tipo"): esquema.TIPOS_PROVEEDOR,
    ("productos", "condicion_venta"): esquema.CONDICIONES_VENTA,
    ("recetas", "tipo"): esquema.TIPOS_RECETA,
    ("recetas", "estado"): esquema.ESTADOS_RECETA,
    ("ventas", "tipo"): esquema.TIPOS_VENTA,
    ("ventas", "medio_pago"): esquema.MEDIOS_PAGO,
    ("ventas", "estado"): esquema.ESTADOS_VENTA,
}

# Claves de negocio que no pueden repetirse.
UNICOS = [("clientes", "dni"), ("farmaceuticos", "matricula"), ("proveedores", "cuit")]

# (entidad origen, campo, entidad referenciada) — sección 2.10 del enunciado.
REFERENCIAS = [
    ("farmaceuticos", "id_sucursal", "sucursales"),
    ("productos", "id_proveedor", "proveedores"),
    ("stock_lotes", "id_producto", "productos"),
    ("stock_lotes", "id_sucursal", "sucursales"),
    ("recetas", "id_cliente", "clientes"),
    ("ventas", "id_cliente", "clientes"),
    ("ventas", "id_farmaceutico", "farmaceuticos"),
    ("ventas", "id_receta", "recetas"),
    ("detalle_ventas", "id_venta", "ventas"),
    ("detalle_ventas", "id_producto", "productos"),
]


def validar(datos: dict[str, list[dict]]) -> list[str]:
    """Devuelve la lista de errores de `datos` (vacía si todo está bien)."""
    errores = _validar_estructura(datos)
    return errores or _validar_negocio(datos)


def _validar_estructura(datos: dict[str, list[dict]]) -> list[str]:
    errores: list[str] = []
    ids: dict[str, set[str]] = {}

    for entidad, (campo_id, prefijo) in IDS.items():
        patron = re.compile(rf"^{prefijo}\d+$")
        vistos: set[str] = set()
        for fila in datos[entidad]:
            identificador = fila[campo_id]
            etiqueta = f"{entidad} {identificador}"
            if identificador is None or not patron.match(identificador):
                errores.append(f"{etiqueta}: id inválido, se esperaba {prefijo} + dígitos")
            elif identificador in vistos:
                errores.append(f"{etiqueta}: id repetido")
            else:
                vistos.add(identificador)
            for campo, valor in fila.items():
                if valor is None:
                    if (entidad, campo) not in NULABLES:
                        errores.append(f"{etiqueta}: el campo {campo} está vacío")
                    continue
                permitidos = ENUMS.get((entidad, campo))
                if permitidos and valor not in permitidos:
                    errores.append(f"{etiqueta}: {campo}={valor!r} no es un valor permitido")
        ids[entidad] = vistos

    for entidad, campo in UNICOS:
        repetidos = Counter(f[campo] for f in datos[entidad] if f[campo] is not None)
        for valor, veces in repetidos.items():
            if veces > 1:
                errores.append(f"{entidad}: {campo}={valor!r} aparece {veces} veces")

    for origen, campo, destino in REFERENCIAS:
        campo_id = IDS[origen][0]
        for fila in datos[origen]:
            valor = fila[campo]
            if valor is not None and valor not in ids[destino]:
                errores.append(f"{origen} {fila[campo_id]}: {campo}={valor!r} no existe en {destino}")

    return errores


def _validar_negocio(datos: dict[str, list[dict]]) -> list[str]:
    errores: list[str] = []
    sucursales = {s["id_sucursal"]: s for s in datos["sucursales"]}
    farmaceuticos = {f["id_farmaceutico"]: f for f in datos["farmaceuticos"]}
    productos = {p["id_producto"]: p for p in datos["productos"]}
    recetas = {r["id_receta"]: r for r in datos["recetas"]}

    for c in datos["clientes"]:
        sin_cobertura = c["obra_social"] == esquema.SIN_COBERTURA
        if sin_cobertura != (c["nro_afiliado"] is None):
            errores.append(
                f"clientes {c['id_cliente']}: nro_afiliado debe estar vacío solo si es 'Sin cobertura'"
            )

    for p in datos["productos"]:
        if p["precio_unit"] <= 0:
            errores.append(f"productos {p['id_producto']}: precio_unit debe ser mayor a 0")

    for lote in datos["stock_lotes"]:
        if lote["unidades"] < 0:
            errores.append(f"stock_lotes {lote['id_lote']}: unidades negativas")

    items_por_venta: dict[str, list[dict]] = defaultdict(list)
    for d in datos["detalle_ventas"]:
        if d["cantidad"] <= 0 or d["precio_unit"] <= 0:
            errores.append(f"detalle_ventas {d['id_detalle']}: cantidad y precio_unit deben ser mayores a 0")
        items_por_venta[d["id_venta"]].append(d)

    dispensas_por_receta: Counter = Counter()
    for v in datos["ventas"]:
        etiqueta = f"ventas {v['id_venta']}"
        items = items_por_venta[v["id_venta"]]
        if not items:
            errores.append(f"{etiqueta}: no tiene ítems en detalle_ventas")
        suma = sum(i["cantidad"] * i["precio_unit"] for i in items)
        if suma != v["total"]:
            errores.append(f"{etiqueta}: total {v['total']} distinto de la suma de ítems {suma}")

        con_receta = v["id_receta"] is not None
        if con_receta != (v["tipo"] == "Con receta"):
            errores.append(f"{etiqueta}: tipo {v['tipo']!r} no coincide con tener o no receta")
        if con_receta and recetas[v["id_receta"]]["id_cliente"] != v["id_cliente"]:
            errores.append(f"{etiqueta}: la receta {v['id_receta']} es de otro cliente")
        if not con_receta and any(
            productos[i["id_producto"]]["condicion_venta"] != esquema.VENTA_LIBRE for i in items
        ):
            errores.append(f"{etiqueta}: incluye productos bajo receta y no tiene receta")

        sucursal = sucursales[farmaceuticos[v["id_farmaceutico"]]["id_sucursal"]]
        if sucursal["tipo"] != "Farmacia":
            errores.append(f"{etiqueta}: el farmacéutico {v['id_farmaceutico']} no es de una Farmacia")

        if con_receta and v["estado"] == "Completada":
            dispensas_por_receta[v["id_receta"]] += 1

    for r in datos["recetas"]:
        etiqueta = f"recetas {r['id_receta']}"
        autorizadas, realizadas = r["dispensas_autorizadas"], r["dispensas_realizadas"]
        prolongado = r["tipo"] == esquema.TRATAMIENTO_PROLONGADO
        if prolongado and not 1 <= autorizadas <= 3:
            errores.append(f"{etiqueta}: un tratamiento prolongado admite de 1 a 3 dispensas")
        if not prolongado and autorizadas != 1:
            errores.append(f"{etiqueta}: una receta {r['tipo']} tiene una única dispensa")
        if not 0 <= realizadas <= autorizadas:
            errores.append(f"{etiqueta}: dispensas_realizadas fuera de rango")
        if r["estado"] == "Completada" and realizadas != autorizadas:
            errores.append(f"{etiqueta}: está Completada pero le quedan dispensas")
        if r["estado"] == "Vigente" and realizadas >= autorizadas:
            errores.append(f"{etiqueta}: está Vigente pero no le quedan dispensas")
        if r["proxima_dispensa"] is not None and not (prolongado and r["estado"] == "Vigente"):
            errores.append(
                f"{etiqueta}: proxima_dispensa solo corresponde a un tratamiento prolongado Vigente"
            )
        completadas = dispensas_por_receta[r["id_receta"]]
        if completadas != realizadas:
            errores.append(
                f"{etiqueta}: dispensas_realizadas={realizadas} pero tiene {completadas} "
                "venta(s) Completada(s)"
            )

    return errores
