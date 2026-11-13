.PHONY: verificar cargar reconstruir-vistas consulta demo test

PYTHON ?= python
export PYTHONPATH := src

## Comprueba Mongo (replica set + transacción) y Redis
verificar:
	$(PYTHON) scripts/verificar_entorno.py

## Carga los CSV (originales + adicionales). REINICIA las colecciones al estado inicial.
## Opcional: make cargar ARGS="--sin-desplazar"
cargar:
	$(PYTHON) -m farmared.carga $(ARGS)

## Rearma las vistas de Redis a partir de MongoDB
reconstruir-vistas:
	$(PYTHON) -m farmared.vistas

## Ejecuta una consulta: make consulta Q=q05   |   make consulta Q=q03 ARGS="C001"
consulta:
	$(PYTHON) -m farmared.consultas $(Q) $(ARGS)

## Muestra el antes/después de q14 + q15 (modifica datos: correr make cargar después)
demo:
	$(PYTHON) scripts/demo_venta.py

## Corre los tests (usan la base farmared_test y la db 15 de Redis)
test:
	$(PYTHON) -m pytest
