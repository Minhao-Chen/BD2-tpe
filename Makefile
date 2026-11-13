.PHONY: verificar mongo-shell redis-cli

PYTHON ?= python

## Comprueba Mongo (replica set + transacción) y Redis
verificar:
	$(PYTHON) scripts/verificar_entorno.py

## Abre mongosh dentro del contenedor de Mongo
mongo-shell:
	docker exec -it farmared-mongo mongosh farmared

## Abre redis-cli dentro del contenedor de Redis
redis-cli:
	docker exec -it farmared-redis redis-cli
