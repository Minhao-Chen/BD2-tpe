"""Lectura de los CSV: de texto a filas con tipos.

Convenciones del enunciado: UTF-8, separador coma, campo vacío = nulo, booleanos True/False,
fechas AAAA-MM-DD, importes enteros.
"""

import csv
from datetime import date
from pathlib import Path
from typing import Callable

from farmared.errores import ErrorCarga


def _texto(valor: str) -> str:
    return valor


def _entero(valor: str) -> int:
    return int(valor)


def _booleano(valor: str) -> bool:
    if valor == "True":
        return True
    if valor == "False":
        return False
    raise ValueError("se esperaba True o False")


def _fecha(valor: str) -> date:
    return date.fromisoformat(valor)


T, E, B, F = _texto, _entero, _booleano, _fecha

# entidad (= nombre del archivo sin .csv) -> columnas en orden, con su conversor
COLUMNAS: dict[str, dict[str, Callable]] = {
    "clientes": {
        "id_cliente": T, "nombre": T, "apellido": T, "dni": T, "email": T, "telefono": T,
        "ciudad": T, "provincia": T, "obra_social": T, "nro_afiliado": T, "activo": B,
    },
    "sucursales": {
        "id_sucursal": T, "nombre": T, "tipo": T, "direccion": T, "ciudad": T, "provincia": T,
        "telefono": T, "activo": B,
    },
    "farmaceuticos": {
        "id_farmaceutico": T, "nombre": T, "apellido": T, "matricula": T, "cargo": T,
        "id_sucursal": T, "activo": B,
    },
    "proveedores": {
        "id_proveedor": T, "razon_social": T, "cuit": T, "tipo": T, "ciudad": T, "provincia": T,
        "telefono": T, "activo": B,
    },
    "productos": {
        "id_producto": T, "nombre": T, "principio_activo": T, "categoria": T, "presentacion": T,
        "condicion_venta": T, "precio_unit": E, "id_proveedor": T, "activo": B,
    },
    "stock_lotes": {
        "id_lote": T, "id_producto": T, "id_sucursal": T, "nro_lote": T, "unidades": E,
        "vencimiento": F,
    },
    "recetas": {
        "id_receta": T, "id_cliente": T, "medico": T, "matricula_medico": T, "fecha_emision": F,
        "tipo": T, "dispensas_autorizadas": E, "dispensas_realizadas": E, "proxima_dispensa": F,
        "estado": T,
    },
    "ventas": {
        "id_venta": T, "id_cliente": T, "id_farmaceutico": T, "id_receta": T, "fecha": F,
        "tipo": T, "medio_pago": T, "total": E, "estado": T,
    },
    "detalle_ventas": {
        "id_detalle": T, "id_venta": T, "id_producto": T, "cantidad": E, "precio_unit": E,
    },
}

ENTIDADES: list[str] = list(COLUMNAS)


def leer_csv(ruta: Path, entidad: str) -> list[dict]:
    """Lee un CSV de `entidad` y devuelve sus filas tipadas (campo vacío -> None).

    Lanza `ErrorCarga` con todos los problemas de formato del archivo.
    """
    columnas = COLUMNAS[entidad]
    filas: list[dict] = []
    errores: list[str] = []
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo)
        if lector.fieldnames != list(columnas):
            raise ErrorCarga([
                f"{ruta.name}: encabezado {lector.fieldnames}, se esperaba {list(columnas)}"
            ])
        for nro_linea, cruda in enumerate(lector, start=2):
            if None in cruda or None in cruda.values():
                errores.append(f"{ruta.name}:{nro_linea}: cantidad de columnas incorrecta")
                continue
            fila = {}
            for campo, convertir in columnas.items():
                valor = cruda[campo].strip()
                try:
                    fila[campo] = convertir(valor) if valor else None
                except ValueError as e:
                    errores.append(f"{ruta.name}:{nro_linea}: {campo}={valor!r} inválido ({e})")
            filas.append(fila)
    if errores:
        raise ErrorCarga(errores)
    return filas


def leer_directorio(directorio: Path, obligatorio: bool) -> dict[str, list[dict]]:
    """Lee los 9 CSV de un directorio.

    Con `obligatorio=True` deben estar todos; si no, los que falten cuentan como vacíos.
    """
    datos: dict[str, list[dict]] = {}
    faltantes: list[str] = []
    for entidad in ENTIDADES:
        ruta = directorio / f"{entidad}.csv"
        if ruta.exists():
            datos[entidad] = leer_csv(ruta, entidad)
        else:
            datos[entidad] = []
            faltantes.append(ruta.name)
    if obligatorio and faltantes:
        raise ErrorCarga([f"falta el archivo {directorio / nombre}" for nombre in faltantes])
    return datos
