"""Salida por consola: resultados de consultas como JSON legible."""

import json
from datetime import date, datetime, time


def _serializar(valor):
    if isinstance(valor, datetime):
        # Las fechas de negocio se guardan a medianoche: se muestran solo como día.
        return valor.date().isoformat() if valor.time() == time.min else valor.isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    raise TypeError(f"no se puede serializar {type(valor).__name__}")


def a_json(dato) -> str:
    """Texto JSON con acentos, sangría y fechas en formato ISO."""
    return json.dumps(dato, ensure_ascii=False, indent=2, default=_serializar)
