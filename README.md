# FarmaRed — TPO Bases de Datos II

Backoffice de una red de farmacias con persistencia políglota **MongoDB + Redis**, en **Python 3.12**.
El enunciado está en [docs/enunciado.pdf](docs/enunciado.pdf).

## Abrir en GitHub Codespaces

1. En GitHub: **Code → Codespaces → Create codespace on main**.
2. Esperar a que termine de construir. El devcontainer (`.devcontainer/devcontainer.json`) levanta
   `docker-compose.yml` con tres servicios:
   - `app`: Python 3.12, donde se abre la terminal y el workspace (`/workspace`);
   - `mongo`: MongoDB 7 como **replica set de un nodo (`rs0`)**, con volumen `mongo-data`.
     El replica set se inicializa solo desde el healthcheck (`rs.initiate()` si todavía no existe);
     `app` no arranca hasta que Mongo es PRIMARY;
   - `redis`: Redis 7.
3. Al crearse, el contenedor corre `pip install -r requirements.txt` y copia `.env.example` a `.env`.

No hay pasos manuales adicionales.

> Fuera de Codespaces: con VS Code + extensión *Dev Containers*, **Reopen in Container** hace lo mismo.

## Verificar el entorno

```bash
make verificar
```

Comprueba la conexión a Mongo, que el replica set esté activo con un PRIMARY, corre una transacción de
prueba (commit y abort) en una colección temporal que después borra, y prueba Redis (`PING`, `SET`/`GET`).
Imprime `[OK]` o `[ERROR]` por paso y termina con código 1 si algo falla.

## Conectarse desde la terminal

```bash
make mongo-shell   # mongosh sobre la base farmared
make redis-cli     # redis-cli
```

Equivalen a `docker exec -it farmared-mongo mongosh farmared` y `docker exec -it farmared-redis redis-cli`.
Desde Python:

```python
from farmared.db import get_mongo_db, get_redis
db = get_mongo_db()   # base farmared
r = get_redis()
```

Variables de entorno (`.env`): `MONGO_URI`, `MONGO_DB`, `REDIS_URL`. Ver [.env.example](.env.example).

## Estructura

```
.devcontainer/          configuración de Codespaces
data/original/          CSV provistos por la cátedra
data/extra/             registros adicionales del equipo
docs/                   enunciado e informe
scripts/                scripts de utilidad (verificar_entorno.py)
src/farmared/           código fuente
  config.py             variables de entorno
  db.py                 conexiones a Mongo y Redis
  carga/                carga de datos (pendiente)
  consultas/            consultas q01–q15 (pendiente)
tests/                  tests (pendiente)
docker-compose.yml
Makefile
requirements.txt
```
