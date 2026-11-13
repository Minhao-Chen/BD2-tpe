"""Uso: python -m farmared.carga [--sin-desplazar]     (o: make cargar)"""

import argparse
import sys

from farmared.carga.cargador import cargar
from farmared.errores import ErrorCarga
from farmared.salida import a_json


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m farmared.carga",
        description="Carga los CSV en MongoDB y Redis. Reinicia las colecciones al estado inicial.",
    )
    parser.add_argument(
        "--sin-desplazar",
        action="store_true",
        help="carga las fechas de data/extra tal cual, sin moverlas a la fecha actual",
    )
    args = parser.parse_args()
    try:
        resumen = cargar(desplazar=not args.sin_desplazar)
    except ErrorCarga as e:
        print(f"[ERROR] carga rechazada, no se escribió nada.\n{e}", file=sys.stderr)
        return 1
    print(a_json(resumen))
    print("Carga OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
