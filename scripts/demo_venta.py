"""Muestra el estado de los datos antes y después de q14 + q15, con casos de rechazo.

Uso: make demo   (o: python scripts/demo_venta.py)

Pensado para sacar los ejemplos del informe. Parte del estado inicial, así que conviene
correr `make cargar` antes; como registra una venta real, correr `make cargar` también después.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farmared.consultas.q14_registrar_venta import registrar_venta  # noqa: E402
from farmared.consultas.q15_descontar_stock import descontar_stock  # noqa: E402
from farmared.db import get_mongo_db  # noqa: E402
from farmared.errores import ErrorValidacion  # noqa: E402
from farmared.salida import a_json  # noqa: E402

db = get_mongo_db()


def estado(id_receta: str | None, id_sucursal: str, productos: list[str]) -> dict:
    """Foto de lo que una venta puede modificar: cantidad de ventas, receta y lotes."""
    return {
        "cantidad_ventas": db.ventas.count_documents({}),
        "receta": db.recetas.find_one({"_id": id_receta}) if id_receta else None,
        "lotes": list(
            db.stock_lotes.find({"id_sucursal": id_sucursal, "id_producto": {"$in": productos}})
            .sort([("id_producto", 1), ("vencimiento", 1)])
        ),
    }


def caso(titulo, id_receta, id_sucursal, productos, operacion) -> dict | None:
    print(f"\n{'=' * 80}\n{titulo}\n{'=' * 80}")
    print("ANTES:\n" + a_json(estado(id_receta, id_sucursal, productos)))
    resultado = None
    try:
        resultado = operacion()
        print("RESULTADO:\n" + a_json(resultado))
    except ErrorValidacion as e:
        print(f"RECHAZADO ({type(e).__name__}): {e}")
    print("DESPUÉS:\n" + a_json(estado(id_receta, id_sucursal, productos)))
    return resultado


def main() -> None:
    ok = caso(
        "1. Venta con receta simple: se registra, la receta se completa y baja el stock",
        "RC006", "S004", ["PRD007"],
        lambda: registrar_venta(
            "C007", "F006", [{"id_producto": "PRD007", "cantidad": 1}], "Débito", id_receta="RC006"
        ),
    )
    caso(
        "2. Rechazo por stock: se piden 23 unidades de PRD004 y hay 22 (nada cambia)",
        "RC002", "S004", ["PRD004"],
        lambda: registrar_venta(
            "C003", "F006", [{"id_producto": "PRD004", "cantidad": 23}], "Obra social", id_receta="RC002"
        ),
    )
    caso(
        "3. Rechazo por validación: producto bajo receta sin receta",
        None, "S001", ["PRD003"],
        lambda: registrar_venta("C001", "F001", [{"id_producto": "PRD003", "cantidad": 1}], "Efectivo"),
    )
    if ok:
        id_venta = ok["venta"]["_id"]
        caso(
            f"4. q15 sobre la venta {id_venta}, que ya tiene el stock descontado: se rechaza",
            None, "S004", ["PRD007"],
            lambda: descontar_stock(id_venta),
        )


if __name__ == "__main__":
    main()
