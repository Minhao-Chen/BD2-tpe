"""Excepciones de dominio.

Los servicios de escritura rechazan una operación lanzando `ErrorValidacion` (o una subclase).
Dentro de una transacción de MongoDB, esa excepción provoca el abort: no queda ningún cambio.
"""


class ErrorFarmaRed(Exception):
    """Base de todos los errores propios del sistema."""


class ErrorValidacion(ErrorFarmaRed):
    """La operación se rechaza porque viola una validación o regla de negocio."""


class StockInsuficiente(ErrorValidacion):
    """El stock vigente de la sucursal no alcanza para algún producto.

    `faltantes` es una lista de {id_producto, solicitado, disponible}.
    """

    def __init__(self, faltantes: list[dict]):
        self.faltantes = faltantes
        detalle = ", ".join(
            f"{f['id_producto']} (pedido {f['solicitado']}, disponible {f['disponible']})"
            for f in faltantes
        )
        super().__init__(f"stock vigente insuficiente: {detalle}")


class ErrorCarga(ErrorFarmaRed):
    """Los CSV no pasan la validación; `errores` lista todos los problemas encontrados."""

    def __init__(self, errores: list[str]):
        self.errores = errores
        super().__init__(f"{len(errores)} error(es) en los datos:\n- " + "\n- ".join(errores))
