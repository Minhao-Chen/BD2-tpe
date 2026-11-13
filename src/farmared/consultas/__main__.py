"""Ejecuta una consulta por su código e imprime el resultado como JSON.

Uso: python -m farmared.consultas q05 [argumentos]      (o: make consulta Q=q05 ARGS="...")

El código (q01 ... q15) se busca entre los módulos de este paquete cuyo nombre empieza con
`qNN_`. Cada módulo define `cli(argv)`, que interpreta sus argumentos y devuelve el resultado.
Para agregar una consulta alcanza con crear su módulo: este archivo no se toca.
"""

import importlib
import pkgutil
import sys

import farmared.consultas as paquete
from farmared.errores import ErrorValidacion
from farmared.salida import a_json


def _modulos() -> dict[str, str]:
    """{'q01': 'q01_productos_proveedor', ...} con las consultas implementadas."""
    return {
        info.name.split("_")[0]: info.name
        for info in pkgutil.iter_modules(paquete.__path__)
        if info.name.startswith("q") and "_" in info.name
    }


def main(argv: list[str]) -> int:
    modulos = _modulos()
    if not argv or argv[0].lower() not in modulos:
        print("Uso: python -m farmared.consultas <consulta> [argumentos]", file=sys.stderr)
        print("Consultas implementadas:", file=sys.stderr)
        for codigo, nombre in sorted(modulos.items()):
            print(f"  {codigo}  ({nombre})", file=sys.stderr)
        return 2
    modulo = importlib.import_module(f"farmared.consultas.{modulos[argv[0].lower()]}")
    try:
        resultado = modulo.cli(argv[1:])
    except ErrorValidacion as e:
        print(f"RECHAZADO: {e}", file=sys.stderr)
        return 1
    print(a_json(resultado))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
