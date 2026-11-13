"""Reglas de fecha del sistema, en un solo lugar.

Ninguna consulta ni servicio usa fechas fijas: todo parte de `hoy()`, que es la fecha del
sistema en la zona horaria del negocio. Las funciones que dependen de la fecha reciben un
parámetro opcional `hoy` solo para poder probarlas con un día conocido.

Definiciones usadas en todo el proyecto:
- últimos N días: `hace_dias(hoy, N) <= fecha <= hoy`
- mes actual:     `primer_dia <= fecha < primer_dia_del_mes_siguiente`  (ver `limites_mes`)
- último año:     `fecha >= un_anio_atras(hoy)`
- lote vigente:   `vencimiento >= hoy`  (el día del vencimiento todavía se puede dispensar)

En MongoDB las fechas se guardan como Date a medianoche UTC del día de negocio.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from farmared import config


def hoy() -> date:
    """Fecha actual del sistema en la zona horaria del negocio."""
    return datetime.now(ZoneInfo(config.ZONA_HORARIA)).date()


def resolver_hoy(valor: date | None) -> date:
    """Devuelve `valor` si se pasó uno (tests) o la fecha del sistema."""
    return valor if valor is not None else hoy()


def a_datetime(d: date | None) -> datetime | None:
    """Convierte una fecha al `datetime` que guarda MongoDB (medianoche UTC)."""
    return None if d is None else datetime(d.year, d.month, d.day)


def hace_dias(desde: date, dias: int) -> date:
    """Primer día de una ventana de `dias` días que termina en `desde`."""
    return desde - timedelta(days=dias)


def limites_mes(d: date) -> tuple[date, date]:
    """Primer día del mes de `d` y primer día del mes siguiente (límite excluido)."""
    primero = d.replace(day=1)
    siguiente = (primero + timedelta(days=32)).replace(day=1)
    return primero, siguiente


def un_anio_atras(d: date) -> date:
    """Mismo día del año anterior (29/02 pasa a 28/02)."""
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def clave_mes(d: date) -> str:
    """Mes de `d` como 'AAAA-MM' (sufijo de las claves de ingresos en Redis)."""
    return d.strftime("%Y-%m")
