# FarmaRed — TPO Bases de Datos II

Backoffice de una red de farmacias con persistencia políglota **MongoDB + Redis**, en **Python 3.12**.

- **MongoDB** (documentos) es la fuente de verdad: clientes, sucursales, farmacéuticos, proveedores,
  productos, stock por lote, recetas y ventas (con sus ítems embebidos).
- **Redis** (clave-valor) es el modelo de lectura: catálogo con proveedor, ranking de productos e
  ingresos por farmacéutico y mes. Se reconstruye desde MongoDB.


## Abrir en GitHub Codespaces

1. En GitHub: **Code → Codespaces → Create codespace on main**.
2. Esperar a que termine de construir. El devcontainer (`.devcontainer/devcontainer.json`) levanta
   `docker-compose.yml` con tres servicios:
   - `app`: Python 3.12, donde se abre la terminal y el workspace (`/workspace`);
   - `mongo`: MongoDB 7 como **replica set de un nodo (`rs0`)**, con volumen `mongo-data`.
     El replica set se inicializa solo desde el healthcheck (`rs.initiate()` si todavía no existe);
     `app` no arranca hasta que Mongo es PRIMARY;
   - `redis`: Redis 7, sin persistencia (solo guarda datos derivados).
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

## Cargar los datos

```bash
make cargar
```

Lee los CSV de `data/original/` y los registros adicionales de `data/extra/`, valida todo (ids,
referencias entre archivos, valores permitidos, totales, recetas) y, si no hay errores, deja MongoDB
y Redis en el estado inicial. Si hay errores los lista y no escribe nada.

**La carga reinicia las colecciones**: borra las ventas, altas y descuentos de stock hechos después.
Por eso se puede repetir las veces que haga falta y siempre deja lo mismo.

Las fechas de `data/extra/` se desplazan a la fecha actual: se escriben tomando como "hoy" la fecha
de `data/extra/FECHA_REFERENCIA` y al cargar se les suma la diferencia con la fecha del sistema.
Así los registros "recientes" siguen siéndolo cualquier día que se cargue. Los CSV originales no se
tocan. `make cargar ARGS="--sin-desplazar"` carga las fechas tal cual están escritas.

## Ejecutar las consultas

```bash
make consulta Q=<código> ARGS="<argumentos>"
```

Imprime el resultado como JSON. Sin `Q` lista las consultas implementadas. Los rechazos por
validación se informan como `RECHAZADO: <motivo>` y código de salida 1.

| Consulta | Qué hace | Motor | Ejemplo |
|---|---|---|---|
| q01 | Productos activos con los datos de su proveedor | Redis | `make consulta Q=q01` |
| q02 | Ventas pendientes con farmacéutico y sucursal | MongoDB | `make consulta Q=q02` |
| q03 | Historial completo de un cliente | MongoDB | `make consulta Q=q03 ARGS="C001"` |
| q04 | Clientes con más de una receta | MongoDB | `make consulta Q=q04` |
| q05 | Farmacéuticos activos y ventas de los últimos 60 días | MongoDB | `make consulta Q=q05` |
| q06 | Recetas con próxima dispensa vencida | MongoDB | `make consulta Q=q06` |
| q07 | Top 5 de productos más vendidos | Redis | `make consulta Q=q07` |
| q08 | Lotes con menos de 50 unidades | MongoDB | `make consulta Q=q08` |
| q09 | Ventas libres menores a $5.000 no anuladas | MongoDB | `make consulta Q=q09` |
| q10 | Clientes atendidos en una sucursal | MongoDB | `make consulta Q=q10 ARGS="S001"` |
| q11 | Ingresos por farmacéutico del mes actual | Redis + MongoDB | `make consulta Q=q11` |
| q12 | Clientes sin ventas en el último año | MongoDB | `make consulta Q=q12` |
| q14 | Registra una venta Completada (valida, actualiza receta, descuenta stock) | MongoDB + Redis | `make consulta Q=q14 ARGS="--cliente C007 --farmaceutico F006 --receta RC006 --item PRD007:1 --medio-pago Débito"` |
| q15 | Descuenta el stock de una venta registrada (FEFO) | MongoDB | `make consulta Q=q15 ARGS="V017"` |

En q14, `--item PRODUCTO:CANTIDAD` se puede repetir y `--receta` es opcional (obligatoria si algún
producto es bajo receta). q14 ya llama a q15 dentro de la misma transacción: q15 por separado solo
aplica a una venta Completada que todavía no tenga el stock descontado.

Cada consulta vive en su propio módulo de `src/farmared/consultas/`, con su documentación
(propósito, parámetros, retorno y motor) al principio del archivo.

`make demo` muestra el estado de los datos antes y después de q14 + q15, con casos de rechazo.
Registra una venta real: correr `make cargar` después para volver al estado inicial.

## Tests

```bash
make test
```

Corren contra el MongoDB y el Redis del entorno, pero en la base `farmared_test` y la db 15 de Redis:
no tocan los datos cargados con `make cargar`.

## Conectarse desde la terminal

```bash
make mongo-shell          # mongosh sobre la base farmared
make redis-cli            # redis-cli
make reconstruir-vistas   # rearma las vistas de Redis desde MongoDB
```

Desde Python:

```python
from farmared.db import get_mongo_db, get_redis
db = get_mongo_db()   # base farmared
r = get_redis()
```

Variables de entorno (`.env`): `MONGO_URI`, `MONGO_DB`, `REDIS_URL`, `FARMARED_TZ`.
Ver [.env.example](.env.example).

## Estructura

```
.devcontainer/          configuración de Codespaces
data/original/          CSV provistos por la cátedra
data/extra/             registros adicionales del equipo + FECHA_REFERENCIA
scripts/                verificar_entorno.py, demo_venta.py
src/farmared/           código fuente
  config.py             variables de entorno
  db.py                 conexiones a Mongo y Redis
  esquema.py            colecciones, validadores e índices de MongoDB
  vistas.py             modelo de lectura en Redis
  fechas.py             "hoy" y ventanas de tiempo
  ids.py                generación de ids nuevos
  errores.py            excepciones de dominio
  carga/                lectura, validación y carga de los CSV
  consultas/            un módulo por consulta (qNN_nombre.py)
tests/                  tests
docker-compose.yml
Makefile
requirements.txt
justificaciones.txt     decisiones de diseño
proximos_pasos.txt      trabajo pendiente
```
