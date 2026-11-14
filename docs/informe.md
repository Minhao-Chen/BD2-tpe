# FarmaRed — Sistema de gestión de una red de farmacias

**Bases de Datos II — Trabajo Práctico Obligatorio — 2.º cuatrimestre 2026**

| | |
|---|---|
| Integrantes | Joaquín Abraldes · Mateo Andraca · Minhao Chen · Santiago Griscan |
| Repositorio | https://github.com/Minhao-Chen/BD2-tpe |
| Motores | MongoDB 7 (documentos) + Redis 7 (clave-valor) |
| Lenguaje | Python 3.12 (pymongo, redis-py) |
| Entorno | GitHub Codespaces (devcontainer + docker-compose) |

---

## 1. Introducción

FarmaRed S.A. administra su backoffice con planillas de cálculo. Este trabajo reemplaza esas
planillas por una arquitectura de persistencia políglota con dos motores NoSQL de paradigmas
distintos: **MongoDB**, orientado a documentos, y **Redis**, clave-valor.

El sistema carga los nueve datasets provistos más registros propios, implementa las 15
consultas y servicios pedidos (q01 a q15) y se levanta completo en GitHub Codespaces sin pasos
manuales. Cada consulta vive en un módulo propio de `src/farmared/consultas/` y se ejecuta desde
la terminal con `make consulta Q=qNN`.

---

## 2. Arquitectura políglota

### 2.1 Visión general

```
                         ┌──────────────────────────────────────┐
   CSV originales  ──►   │  Carga (validación + transformación) │
   CSV adicionales ──►   └───────────────┬──────────────────────┘
                                         │ escribe
                                         ▼
               ┌───────────────────────────────────────────────┐
               │ MongoDB (replica set rs0) — FUENTE DE VERDAD  │
               │ clientes · sucursales · farmaceuticos ·       │
               │ proveedores · productos · stock_lotes ·       │
               │ recetas · ventas (ítems embebidos)            │
               └──────┬──────────────────────────▲─────────────┘
          reconstruye │                          │ lecturas, agregaciones
          / incrementa│                          │ y transacciones
                      ▼                          │
               ┌──────────────────────┐   ┌──────┴───────────────────┐
               │ Redis — MODELO DE    │◄──│ Consultas y servicios    │
               │ LECTURA (derivado)   │   │ q01 … q15 (Python)       │
               │ catálogo · ranking · │   └──────────────────────────┘
               │ ingresos por mes     │
               └──────────────────────┘
```

**MongoDB es la única fuente de verdad.** Toda escritura de negocio va primero a MongoDB.
**Redis guarda vistas derivadas** que se pueden reconstruir en cualquier momento desde MongoDB.
Por eso Redis corre sin persistencia: si se reinicia vacío, la primera consulta que lo necesita
reconstruye las vistas sola (`vistas.asegurar()`).

### 2.2 Por qué MongoDB

- **Estructura jerárquica.** Una venta es una cabecera con una cantidad variable de ítems. En un
  documento eso se modela de forma natural: la venta y sus ítems se leen y escriben juntos, sin
  joins.
- **Esquema flexible pero controlado.** Se usa `$jsonSchema` como validador de cada colección,
  así el motor rechaza documentos mal formados aunque el esquema no sea rígido.
- **Agregaciones.** El *aggregation framework* (`$lookup`, `$group`, `$unionWith`) resuelve las
  consultas que cruzan entidades y los reportes del enunciado.
- **Transacciones multi-documento.** Con un replica set (aunque sea de un nodo), MongoDB ofrece
  transacciones ACID sobre varias colecciones. Las necesitan q14 y q15: venta, receta y lotes se
  confirman o se descartan juntos.
- **Índices secundarios y únicos.** Son los que piden los patrones de acceso: ventas por cliente,
  por farmacéutico y por fecha; lotes por sucursal, producto y vencimiento; DNI, matrícula y CUIT
  únicos.

### 2.3 Por qué Redis

- **Datos de referencia muy leídos y poco modificados.** El catálogo de productos con su
  proveedor se pre-arma en un HASH por producto. La consulta no hace joins: lee estructuras ya
  listas, en memoria.
- **Rankings y acumulados.** Los *sorted sets* (ZSET) mantienen ordenados el ranking de productos
  por unidades vendidas y los ingresos por farmacéutico de cada mes. `ZINCRBY` los actualiza en
  O(log n) con cada venta, sin recalcular todo. Leer el top 5 cuesta O(log n + 5).
- **Desacople.** Los reportes agregados se sirven desde Redis y no compiten con las escrituras
  transaccionales de MongoDB.

### 2.4 Asignación por entidad y caso de uso

| Dato / caso de uso | Características (enunciado 3.2) | Motor | Justificación |
|---|---|---|---|
| Ventas y su detalle | Jerárquica, consultas por cliente / farmacéutico / fecha, alto volumen de inserciones | MongoDB | Un documento por venta con los ítems embebidos. Una inserción es una sola escritura atómica. Índices compuestos `{id_cliente, fecha}` y `{id_farmaceutico, fecha}`. |
| Stock por lote | Actualizaciones frecuentes y concurrentes; nunca negativo; FEFO | MongoDB | Un documento por lote. Se descuenta con `$inc` condicional dentro de una transacción. Índice `{id_sucursal, id_producto, vencimiento}` para el orden FEFO. |
| Clientes, recetas, farmacéuticos | Altas, modificaciones, bajas lógicas; relaciones que se recorren en historiales | MongoDB | Colecciones propias relacionadas por referencia. Validador `$jsonSchema` e índices únicos (DNI, matrícula). |
| Catálogo y proveedores | Baja frecuencia de cambio, alta frecuencia de lectura | MongoDB (verdad) + Redis (lectura) | Redis sirve el catálogo ya unido con el proveedor (q01). |
| Reportes agregados | Totales por farmacéutico, rankings, conteos por período | Redis (ranking e ingresos) + MongoDB (conteos con ventana de fechas) | Los ZSET resuelven q07 y q11. Los conteos con ventanas arbitrarias (q05, q12) se hacen con agregaciones de MongoDB. |

---

## 3. Modelo de datos

### 3.1 MongoDB

#### Decisiones de modelado

| Id | Decisión | Motivo |
|---|---|---|
| D01 | MongoDB es la fuente de verdad; Redis solo guarda datos derivados | Una única fuente evita inconsistencias. Redis puede perderse sin perder información. |
| D02 | El id de negocio (C001, V017…) se usa como `_id` | Los ids del enunciado ya son únicos. Se evita un índice extra y los `$lookup` se hacen contra `_id`. |
| D03 | Los ítems de la venta (`detalle_ventas`) van **embebidos** en la venta | Siempre se leen y escriben con su venta. Tienen tamaño acotado y no tienen vida propia. |
| D04 | Cliente, farmacéutico, receta, producto, proveedor y sucursal se relacionan **por referencia** | Son entidades con ciclo de vida propio (ABM, bajas lógicas) y se comparten entre muchos documentos. Embeberlas obligaría a actualizar copias. |
| D05 | El stock es una colección propia de lotes, no un arreglo dentro del producto | Los lotes se actualizan con mucha frecuencia y de forma concurrente. Un documento por lote reduce los conflictos de escritura a ese lote. |
| D06 | La venta guarda una copia de `id_sucursal` (la del farmacéutico al momento de la venta) | Es un dato histórico: si el farmacéutico cambia de sucursal o se da de baja, la venta sigue perteneciendo a la sucursal donde se hizo. Lo usan q10, q15 y el índice `{id_sucursal}`. |
| D07 | Contacto, domicilio y cobertura del cliente, y los datos del médico en la receta, son subdocumentos | Agrupan atributos que se leen y modifican juntos, por ejemplo cuando q13 cambia contacto y cobertura. |
| D08 | La venta registra `stock_aplicado` y `lotes_consumidos` | `stock_aplicado` hace a q15 idempotente: no descuenta dos veces. `lotes_consumidos` deja trazabilidad de qué lotes se usaron. |

#### Colecciones

```
clientes ─────────────┐ 1                  sucursales ◄──────────────┐
  _id: "C001"         │                      _id: "S001"             │ N:1
  nombre, apellido    │                      nombre, tipo            │
  dni (único)         │                      direccion, ciudad, ...  │
  contacto {email, telefono}                 activo                  │
  domicilio {ciudad, provincia}                                      │
  cobertura {obra_social, nro_afiliado}    farmaceuticos ────────────┘
  activo              │                      _id: "F001"
                      │ N                    matricula (única), cargo
recetas ◄─────────────┤                      id_sucursal ──► sucursales
  _id: "RC001"        │                      activo
  id_cliente ──► clientes                         ▲
  medico {nombre, matricula}                      │ N:1
  fecha_emision, tipo                             │
  dispensas_autorizadas / _realizadas      ventas ┘
  proxima_dispensa, estado                   _id: "V001"
          ▲                                  id_cliente ──► clientes
          │ N:1 (opcional)                   id_farmaceutico ──► farmaceuticos
          └──────────────────────────────── id_receta ──► recetas (o null)
                                             id_sucursal (copia histórica, D06)
proveedores ◄──┐                             fecha, tipo, medio_pago, total, estado
  _id: "PRV001"│ N:1                         items: [ {id_detalle, id_producto ──► productos,
  cuit (único) │                                       cantidad, precio_unit} ]   (embebido, D03)
  tipo, activo │                             stock_aplicado, lotes_consumidos[]
               │
productos ─────┘                           stock_lotes
  _id: "PRD001"                              _id: "L001"
  nombre, principio_activo, categoria        id_producto ──► productos
  presentacion, condicion_venta              id_sucursal ──► sucursales
  precio_unit, id_proveedor, activo          nro_lote, unidades (≥ 0), vencimiento

contadores: {_id: "ventas" | "detalles" | "clientes", prefijo, ancho, seq}
```

#### Validadores e índices

Cada colección se crea con un validador `$jsonSchema`: campos obligatorios, tipos, valores
permitidos (enumerados), enteros con mínimo (`unidades ≥ 0`, `precio_unit ≥ 1`) y `items` con al
menos un elemento.

| Colección | Índice | Uso |
|---|---|---|
| clientes | `{dni}` único | Unicidad de DNI (q13) |
| farmaceuticos | `{matricula}` único · `{id_sucursal}` | Unicidad · farmacéuticos por sucursal |
| proveedores | `{cuit}` único | Unicidad de CUIT |
| productos | `{id_proveedor}` | Productos de un proveedor |
| stock_lotes | `{id_sucursal, id_producto, vencimiento}` · `{unidades}` | FEFO (q15) · lotes con stock bajo (q08) |
| recetas | `{id_cliente}` · `{tipo, estado, proxima_dispensa}` | Recetas por cliente (q03, q04) · dispensas vencidas (q06) |
| ventas | `{id_cliente, fecha}` · `{id_farmaceutico, fecha}` · `{id_sucursal}` · `{estado, fecha}` | Historial (q03, q12) · ventas por farmacéutico (q05) · por sucursal (q10) · por estado (q02, q09) |

### 3.2 Redis

| Clave | Tipo | Contenido | Consulta |
|---|---|---|---|
| `farmared:producto:{id}` | HASH | Producto con los datos de su proveedor ya incluidos (`proveedor_razon_social`, `proveedor_cuit`, …) | q01, q07 (nombres) |
| `farmared:productos:activos` | SET | Ids de productos con `activo = True` | q01 |
| `farmared:ranking:productos` | ZSET | `id_producto → unidades vendidas` (solo ventas Completadas) | q07 |
| `farmared:ingresos:{AAAA-MM}` | ZSET | `id_farmaceutico → ingresos del mes en ARS` (solo Completadas) | q11 |
| `farmared:vistas:ok` | STRING | Marca de que las vistas están construidas | todas las anteriores |

**Mantenimiento de las vistas:**

- `vistas.reconstruir()` las arma completas desde MongoDB en un único `MULTI/EXEC`. La llaman
  la carga y `make reconstruir-vistas`.
- `vistas.asegurar()` reconstruye si falta la marca. Así un Redis reiniciado se repara solo.
- `vistas.aplicar_venta()` suma una venta recién confirmada con `ZINCRBY`, sin recalcular todo.

---

## 4. Integridad referencial y validaciones

Ninguno de los dos motores garantiza integridad referencial. Se resuelve en tres niveles:

1. **En la carga** (`carga/validacion.py`). Antes de escribir nada se valida todo en memoria. Si
   hay algún error, se informa la lista completa y no se escribe ningún documento.
   - Estructura: formato y unicidad de ids, campos obligatorios, valores permitidos, claves de
     negocio únicas (DNI, matrícula, CUIT) y las 10 referencias de la sección 2.10 del enunciado.
   - Reglas de negocio:
     - `nro_afiliado` vacío solo si el cliente no tiene cobertura;
     - el total de cada venta coincide con la suma de sus ítems;
     - el tipo de venta es coherente con tener o no receta, y la receta es del mismo cliente;
     - no hay productos bajo receta en ventas libres;
     - la venta la registra un farmacéutico de una Farmacia;
     - los rangos de dispensas son coherentes con el tipo y el estado de la receta;
     - `dispensas_realizadas` coincide con las ventas Completadas asociadas a cada receta.
2. **En el motor.** Los validadores `$jsonSchema` y los índices únicos rechazan documentos mal
   formados o duplicados, aunque se escriba por fuera de la aplicación.
3. **En los servicios de escritura** (q13, q14, q15). Antes de escribir, cada servicio verifica
   las referencias y su estado. Si algo falla se lanza `ErrorValidacion` y no queda ningún cambio.
   - q14 y q15 lo hacen dentro de la misma transacción: que las entidades existan, que estén
     activas y que la receta sea del mismo cliente. Si algo falla, la transacción aborta.
   - q13 escribe un único documento (atómico) y valida antes de escribir: DNI único, cobertura
     coherente y cliente activo. El índice único `{dni}` cubre las altas simultáneas.

---

## 5. Estrategia de carga de datos

`make cargar` (`python -m farmared.carga`) hace lo siguiente:

1. Lee los 9 CSV de `data/original/`, que son obligatorios, y los de `data/extra/`, que son
   opcionales. Convierte tipos según las convenciones del enunciado: vacío es nulo, `True`/`False`
   son booleanos, fechas ISO e importes enteros.
2. Desplaza las fechas de los registros adicionales (ver 5.2).
3. Valida todo (sección 4). Ante cualquier error no escribe nada.
4. Recrea las colecciones con sus validadores e índices, transforma las filas al modelo de
   documentos (ítems embebidos, subdocumentos, `id_sucursal` copiado) e inserta.
5. Inicializa los contadores de ids (`ventas`, `detalles`, `clientes`) con el mayor número usado.
6. Reconstruye las vistas de Redis.

**Reproducible e idempotente.** La carga siempre lleva las bases al mismo estado inicial definido
por los CSV. Correrla dos veces deja exactamente lo mismo que correrla una. Como contrapartida,
borra lo que hayan registrado los servicios después de la carga.

**Stock histórico.** `stock_lotes.csv` ya es la foto actual del stock. Por eso las ventas
Completadas del historial se cargan con `stock_aplicado = true` y no se vuelven a descontar.

### 5.1 Registros adicionales

Se agregaron **10 registros por colección** (107 filas, contando 19 ítems de venta). Cada uno
apunta a un caso borde concreto de alguna consulta:

| Consulta | Registros y caso que cubren |
|---|---|
| q02 | V024 y V033: ventas Pendientes nuevas, con distintos farmacéuticos y sucursales |
| q03 | C009: receta RC010 y venta V017 el mismo día, para verificar el orden (receta antes que venta) |
| q04 | C009 con 3 recetas, C010 con 2, C011 con 1 (en el límite: no debe aparecer) |
| q05 | V028 a 60 días justos (cuenta) y V029 a 61 días (no cuenta); V027 Anulada (no cuenta); V033 Pendiente (cuenta); F013 activo sin ventas (aparece con 0); F014 inactivo con ventas recientes (no aparece) |
| q06 | Próxima dispensa ayer (RC010, aparece), hoy (RC011, no aparece: la comparación es estricta) y mañana (RC013, no aparece) |
| q07 | V033 Pendiente con 20 unidades y V034 Anulada con 30, que no deben sumar al ranking |
| q08 | L022 con 49 unidades (aparece) y L023 con 50 (no aparece); L024 con 0; L019 vencido con stock; L025 vence en 7 días; L026 de un producto discontinuado |
| q09 | V025 de $4.999 (aparece), V026 de $5.000 (no aparece), V027 Anulada de $2.600 (no aparece) |
| q10 | S012, sucursal dada de baja con ventas de F014 (inactivo); S013 sin ventas (resultado vacío) |
| q11 | Ventas Completadas con fecha "hoy" en S007, S008 y S009, más una Pendiente y una Anulada en el mismo mes que no suman |
| q12 | C012 con última venta hace 1 año justo (no aparece), C013 hace 1 año y 1 día (aparece), C014 sin ventas, C015 inactivo sin ventas |
| q14 / q15 | En S006, PRD015 tiene un lote vencido con stock (L019), uno chico (L020) y uno grande (L021); PRD019 sin stock (L024); RC016 con su última dispensa pendiente; RC012 Vencida; C015 inactivo; PRD023 discontinuado |

Además se incorporan una segunda droguería (S015, con su farmacéutica F017), un proveedor
inactivo (PRV014) y uno sin productos (PRV015). Los clientes nuevos usan todas las coberturas que
admite el enunciado, incluida 'Sin cobertura'.

### 5.2 Fechas relativas

Varias consultas dependen de la fecha del sistema ("hoy", "mes actual", "últimos 60 días",
"último año"). Un registro con fecha fija deja de ser "reciente" con el paso de las semanas.
Para que los casos borde sigan funcionando cualquier día:

- los CSV adicionales se escriben tomando como "hoy" la fecha de `data/extra/FECHA_REFERENCIA`
  (2026-11-13);
- al cargar, a cada fecha adicional se le suma `(fecha del sistema − FECHA_REFERENCIA)`;
- los CSV originales de la cátedra nunca se modifican.

Las consultas calculan "hoy" con la fecha del sistema en la zona horaria del negocio
(`America/Argentina/Buenos_Aires`, configurable con `FARMARED_TZ`). Nunca usan fechas fijas en el
código. Las ventas que q11 necesita en el mes actual tienen exactamente la fecha de referencia,
así que siempre caen en el mes en curso.

---

## 6. Consultas y servicios

Convenciones para toda la sección:

- Todas se ejecutan con `make consulta Q=qNN ARGS="…"` e imprimen el resultado como JSON.
- Los rechazos por validación se muestran como `RECHAZADO: <motivo>` (código de salida 1).
- Los ejemplos son reales, tomados con los registros adicionales cargados el **13/11/2026**.
  Para abreviar se muestran solo algunos campos o filas.

### q01 — Productos activos con los datos de su proveedor

- **Motor:** Redis.
- **Relación:** producto → proveedor se resuelve al **construir la vista**: el HASH de cada
  producto ya trae los campos del proveedor. Leer no requiere joins.

```python
vistas.asegurar()
ids = sorted(r.smembers("farmared:productos:activos"))
pipe = r.pipeline(transaction=False)
for id_producto in ids:
    pipe.hgetall(f"farmared:producto:{id_producto}")
return [vistas.hash_a_producto(campos) for campos in pipe.execute()]
```

**Ejemplo** (20 productos activos; se muestra el primero):

```json
{ "id_producto": "PRD001", "nombre": "Paracetamol 500mg x30", "condicion_venta": "Venta libre",
  "precio_unit": 2800, "activo": true,
  "proveedor": { "id_proveedor": "PRV001", "razon_social": "Laboratorios Andinos S.A.",
                 "cuit": "30-71234567-1", "tipo": "Laboratorio", "ciudad": "Buenos Aires",
                 "provincia": "Buenos Aires", "telefono": "1143001100", "activo": true } }
```

### q02 — Ventas pendientes con farmacéutico y sucursal

- **Motor:** MongoDB (aggregation).
- **Relación:** referencias encadenadas venta → farmacéutico → sucursal con dos `$lookup`. El
  farmacéutico aparece aunque esté inactivo.

```javascript
db.ventas.aggregate([
  { $match: { estado: "Pendiente" } },
  { $lookup: { from: "farmaceuticos", localField: "id_farmaceutico", foreignField: "_id", as: "farmaceutico" } },
  { $unwind: "$farmaceutico" },
  { $lookup: { from: "sucursales", localField: "farmaceutico.id_sucursal", foreignField: "_id", as: "sucursal" } },
  { $unwind: "$sucursal" },
  { $project: { _id: 0, id_venta: "$_id", fecha: 1, total: 1,
                nombre: "$farmaceutico.nombre", apellido: "$farmaceutico.apellido",
                matricula: "$farmaceutico.matricula",
                sucursal: { id_sucursal: "$sucursal._id", nombre: "$sucursal.nombre" } } },
  { $sort: { id_venta: 1 } }
])
```

**Ejemplo:**

| id_venta | fecha | farmacéutico | matrícula | sucursal | total |
|---|---|---|---|---|---|
| V011 | 2026-10-12 | Matías Sandoval | MN-18340 | S004 Farmacia Nueva Córdoba | 4.800 |
| V012 | 2026-10-11 | Natalia Giménez | MN-18289 | S003 Farmacia Rosario Centro | 9.200 |
| V024 | 2026-11-13 | Gonzalo Ríos | MN-18604 | S009 Farmacia Santa Fe Capital | 8.400 |
| V033 | 2026-11-10 | Paula Castro | MN-18502 | S006 Farmacia Caballito | 62.000 |

### q03 — Historial completo de un cliente

- **Parámetro:** `id_cliente`.
- **Motor:** MongoDB (aggregation).
- **Relación:** se combinan dos colecciones que referencian al cliente con `$unionWith`. Ambas
  ramas se proyectan a la misma forma (`tipo_registro`, `id_registro`, `fecha`, …) y se ordenan
  juntas. En un empate de fecha, la receta va antes que la venta. Si el cliente no existe, se
  rechaza.

```javascript
db.ventas.aggregate([
  { $match: { id_cliente: "C009" } },
  { $project: { _id: 0, fecha: 1, tipo_registro: { $literal: "venta" }, id_registro: "$_id",
                tipo: 1, estado: 1, total: 1, /* … campos de receta en null … */ } },
  { $unionWith: { coll: "recetas", pipeline: [
      { $match: { id_cliente: "C009" } },
      { $project: { _id: 0, fecha: "$fecha_emision", tipo_registro: { $literal: "receta" },
                    id_registro: "$_id", tipo: 1, estado: 1, medico: 1, /* … */ } } ] } },
  { $sort: { fecha: 1, tipo_registro: 1, id_registro: 1 } }
])
```

**Ejemplo** (`make consulta Q=q03 ARGS="C009"`):

| fecha | registro | id | tipo | estado | total |
|---|---|---|---|---|---|
| 2026-04-27 | receta | RC012 | Simple | Vencida | — |
| 2026-08-30 | receta | RC010 | Tratamiento prolongado | Vigente | — |
| 2026-08-30 | venta | V017 | Con receta | Completada | 4.300 |
| 2026-10-13 | venta | V018 | Con receta | Completada | 4.300 |
| 2026-10-14 | receta | RC011 | Tratamiento prolongado | Vigente | — |
| 2026-10-14 | venta | V019 | Con receta | Completada | 31.000 |

Rechazo: `make consulta Q=q03 ARGS="C999"` → `RECHAZADO: el cliente C999 no existe`.

### q04 — Clientes con más de una receta

- **Motor:** MongoDB (aggregation).
- **Relación:** primero se agrupa en `recetas` y después se resuelve la referencia al cliente con
  `$lookup`. Así solo se buscan los clientes que superan el umbral.

```javascript
db.recetas.aggregate([
  { $group: { _id: "$id_cliente", cantidad_recetas: { $sum: 1 } } },
  { $match: { cantidad_recetas: { $gt: 1 } } },
  { $lookup: { from: "clientes", localField: "_id", foreignField: "_id", as: "cliente" } },
  { $unwind: "$cliente" },
  { $project: { _id: 0, id_cliente: "$_id", nombre: "$cliente.nombre", apellido: "$cliente.apellido",
                /* … resto de los datos del cliente … */ cantidad_recetas: 1 } },
  { $sort: { cantidad_recetas: -1, id_cliente: 1 } }
])
```

**Ejemplo:** C009 Valentina Morales (3) · C001 Lucía Fernández (2) · C002 Martín Gómez (2) ·
C006 Ricardo Paz (2) · C010 Diego Romero (2). C011, con una sola receta, no aparece.

### q05 — Farmacéuticos activos y ventas de los últimos 60 días

- **Motor:** MongoDB (aggregation).
- **Relación:** se parte de `farmaceuticos` y no de `ventas`, para que los que no tienen ventas
  aparezcan con 0. Un `$lookup` con sub-pipeline filtra las ventas del farmacéutico por fecha y
  estado.
- **Ventana:** `hoy − 60 días ≤ fecha ≤ hoy`, calculada con la fecha del sistema. Las Pendientes
  cuentan; solo se excluyen las Anuladas.

```javascript
db.farmaceuticos.aggregate([
  { $match: { activo: true } },
  { $lookup: { from: "ventas", localField: "_id", foreignField: "id_farmaceutico",
               pipeline: [ { $match: { fecha: { $gte: DESDE, $lte: HOY }, estado: { $ne: "Anulada" } } },
                           { $project: { _id: 1 } } ],
               as: "ventas" } },
  { $project: { _id: 0, id_farmaceutico: "$_id", nombre: 1, apellido: 1, matricula: 1, id_sucursal: 1,
                cantidad_ventas: { $size: "$ventas" } } },
  { $sort: { cantidad_ventas: -1, id_farmaceutico: 1 } }
])
```

**Ejemplo:** F005 y F012 con 3 · F002, F009, F010 y F011 con 2 · F001, F003, F006, F008 y F016
con 1 · F007, F013, F015 y F017 con **0**. F004 y F014 están inactivos y no aparecen.

### q06 — Recetas de tratamiento prolongado con dispensa vencida

- **Motor:** MongoDB (aggregation).
- **Relación:** el filtro usa el índice `{tipo, estado, proxima_dispensa}` y `$lookup` resuelve
  receta → cliente. La comparación es estricta: `proxima_dispensa < hoy`.

```javascript
db.recetas.aggregate([
  { $match: { tipo: "Tratamiento prolongado", estado: "Vigente", proxima_dispensa: { $lt: HOY } } },
  { $lookup: { from: "clientes", localField: "id_cliente", foreignField: "_id", as: "cliente" } },
  { $unwind: "$cliente" },
  { $project: { /* datos de la receta + datos planos del cliente */ } },
  { $sort: { proxima_dispensa: 1, id_receta: 1 } }
])
```

**Ejemplo:**

| receta | cliente | dispensas realizadas | próxima dispensa |
|---|---|---|---|
| RC002 | C003 Ruiz | 2 | 2026-09-15 |
| RC003 | C006 Paz | 2 | 2026-10-01 |
| RC004 | C006 Paz | 1 | 2026-10-20 |
| RC010 | C009 Morales | 2 | 2026-11-12 (ayer) |

RC011 (próxima dispensa hoy) y RC013 (mañana) no aparecen.

### q07 — Top 5 de productos más vendidos

- **Motor:** Redis (ZSET).
- **Relación:** el ranking se mantiene en `farmared:ranking:productos` y solo suma ventas
  Completadas. Los nombres se leen de los HASH de producto con un *pipeline*. Para que el
  resultado sea determinista se toma el quinto puntaje y todos los productos empatados con él, y
  se desempata por id.

```python
primeros = r.zrevrange("farmared:ranking:productos", 0, 4, withscores=True)
limite = primeros[-1][1]
candidatos = r.zrangebyscore("farmared:ranking:productos", limite, "+inf", withscores=True)
candidatos.sort(key=lambda item: (-item[1], item[0]))     # desempate por id
candidatos = candidatos[:5]
# + HGET farmared:producto:{id} nombre  (pipeline)
```

**Ejemplo:** PRD015 Enalapril (7) · PRD005 Metformina (6) · PRD011 Loratadina (6) · PRD001
Paracetamol (5) · PRD004 Losartán (3). Las 20 unidades de V033 (Pendiente) y las 30 de V034
(Anulada) no cuentan.

### q08 — Lotes con menos de 50 unidades

- **Motor:** MongoDB (aggregation).
- **Relación:** tres `$lookup`: lote → producto → proveedor y lote → sucursal. Se calcula
  `vencido` para cada lote y se incluyen lotes vacíos, vencidos y de productos discontinuados.

```javascript
db.stock_lotes.aggregate([
  { $match: { unidades: { $lt: 50 } } },
  { $lookup: { from: "productos", localField: "id_producto", foreignField: "_id", as: "producto" } },
  { $unwind: "$producto" },
  { $lookup: { from: "proveedores", localField: "producto.id_proveedor", foreignField: "_id", as: "proveedor" } },
  { $unwind: "$proveedor" },
  { $lookup: { from: "sucursales", localField: "id_sucursal", foreignField: "_id", as: "sucursal" } },
  { $unwind: "$sucursal" },
  { $project: { /* lote, producto, proveedor, sucursal */ vencido: { $lt: ["$vencimiento", HOY] } } },
  { $sort: { unidades: 1, id_lote: 1 } }
])
```

**Ejemplo** (15 lotes; primeros 6):

| lote | unidades | vencido | producto | sucursal | proveedor |
|---|---|---|---|---|---|
| L024 | 0 | no | Insulina NPH 100UI/ml | Farmacia Caballito | BioAndes Laboratorios S.A. |
| L020 | 3 | no | Enalapril 10mg x30 | Farmacia Caballito | Laboratorios del Plata S.A. |
| L026 | 8 | no | Jarabe antitusivo 120ml | Farmacia Santa Fe Capital | Laboratorio Patagónico S.A. |
| L010 | 12 | no | Alprazolam 0,5mg x30 | Farmacia Rosario Centro | Distribuidora Sur Salud S.A. |
| L025 | 12 | no | Clonazepam 2mg x30 | Farmacia Mar del Plata | Pharma Delta S.R.L. |
| L018 | 15 | **sí** | Alcohol en gel 250ml | Farmacia Belgrano | DroguMed S.R.L. |

El último de la lista es L022 con 49 unidades. L023, con 50, no aparece.

### q09 — Ventas libres menores a $5.000 no anuladas

- **Motor:** MongoDB (`find`). No cruza entidades.

```javascript
db.ventas.find(
  { tipo: "Venta libre", total: { $lt: 5000 }, estado: { $ne: "Anulada" } },
  { fecha: 1, id_cliente: 1, id_farmaceutico: 1, id_sucursal: 1, total: 1, medio_pago: 1, estado: 1 }
).sort({ _id: 1 })
```

**Ejemplo:** V013 ($4.400) · V014 ($4.600) · V025 ($4.999) · V028 ($3.100). V026 ($5.000) y V027
(Anulada) no aparecen.

### q10 — Clientes atendidos en una sucursal

- **Parámetro:** `id_sucursal`.
- **Motor:** MongoDB (aggregation).
- **Relación:** la venta guarda la sucursal del farmacéutico que la registró (decisión D06). Por
  eso la relación "a través del farmacéutico" se resuelve con el dato histórico de la venta, esté
  el farmacéutico activo o no. Se agrupa por cliente y se resuelve la referencia con `$lookup`.
  Si la sucursal no existe, se rechaza.

```javascript
db.ventas.aggregate([
  { $match: { id_sucursal: "S012" } },
  { $group: { _id: "$id_cliente", cantidad_ventas: { $sum: 1 } } },
  { $lookup: { from: "clientes", localField: "_id", foreignField: "_id", as: "cliente" } },
  { $unwind: "$cliente" },
  { $project: { /* datos planos del cliente */ cantidad_ventas: 1 } },
  { $sort: { id_cliente: 1 } }
])
```

**Ejemplos:**

- `S012` (sucursal dada de baja; la venta la registró F014, hoy inactivo) → C018 Joaquín Peralta,
  1 venta.
- `S013` → `[]`.
- `S999` → `RECHAZADO: la sucursal S999 no existe`.

### q11 — Ingresos por farmacéutico del mes actual

- **Motores:** Redis + MongoDB.
- **Relación:** el ZSET `farmared:ingresos:{AAAA-MM}` del mes actual da los ingresos ya
  ordenados (solo ventas Completadas). Los datos de los farmacéuticos se completan con **una**
  consulta `$in` a MongoDB, es decir, combinación en la aplicación.

```python
filas = r.zrevrange(f"farmared:ingresos:{hoy:%Y-%m}", 0, -1, withscores=True)
ids = [id_farmaceutico for id_farmaceutico, _ in filas]
farmaceuticos = {f["_id"]: f for f in db.farmaceuticos.find({"_id": {"$in": ids}})}
```

**Ejemplo** (noviembre de 2026):

| farmacéutico | sucursal | ingresos |
|---|---|---|
| F012 Gonzalo Ríos | S009 | 9.999 |
| F011 Valeria Sosa | S008 | 8.600 |
| F010 Andrés Molina | S007 | 6.800 |

### q12 — Clientes sin ventas en el último año

- **Motor:** MongoDB (aggregation).
- **Relación:** desde `clientes`, un `$lookup` con sub-pipeline obtiene la fecha de la última
  venta de cada cliente (`$max`). Se conservan los clientes sin ventas y los que tienen la
  última venta antes del límite, incluidos los inactivos.
- **Límite:** misma fecha del año anterior. Una venta exactamente en el límite cuenta como
  reciente.

```javascript
db.clientes.aggregate([
  { $lookup: { from: "ventas", localField: "_id", foreignField: "id_cliente",
               pipeline: [ { $group: { _id: null, ultima: { $max: "$fecha" } } } ], as: "ventas" } },
  { $set: { ultima_venta: { $arrayElemAt: ["$ventas.ultima", 0] } } },
  { $match: { $or: [ { ventas: { $size: 0 } }, { ultima_venta: { $lt: HACE_UN_ANIO } } ] } },
  { $project: { /* datos planos del cliente */ ultima_venta: 1 } },
  { $sort: { id_cliente: 1 } }
])
```

**Ejemplo:**

| cliente | activo | última venta |
|---|---|---|
| C004 Navarro | sí | 2025-09-18 |
| C008 Mansilla | no | — |
| C013 Domínguez | sí | 2025-11-12 (un año y un día) |
| C014 Ibarra | sí | — |
| C015 Villalba | no | — |

C012, con su última venta el 2025-11-13 (un año justo), no aparece.

### q13 — ABM de clientes

- **Operaciones:** tres subcomandos, cada uno con su función.
  - `alta`: `alta_cliente(nombre, apellido, dni, email, telefono, ciudad, provincia,
    obra_social, nro_afiliado=None)`.
  - `modificar`: `modificar_cliente(id_cliente, email, telefono, obra_social, nro_afiliado)`.
    Solo cambia los campos que se informan.
  - `baja`: `baja_cliente(id_cliente)`.
- **Motor:** MongoDB, colección `clientes`.
- **Retorno:** `{antes, despues}` con el documento del cliente antes y después de la operación.
  En el alta, `antes` es `null`.

**Validaciones.** Cualquiera que falle lanza `ErrorValidacion` y no escribe nada.

- Los textos son obligatorios, el email debe tener `@` y el DNI debe tener 7 u 8 dígitos sin
  puntos.
- La obra social debe ser uno de los valores del enunciado.
- **Cobertura coherente.** Es la misma regla que aplica la carga: `nro_afiliado` está vacío si y
  solo si el cliente es 'Sin cobertura'.
  - Si se cambia la obra social, hay que informar el número de afiliado nuevo.
  - Pasar a 'Sin cobertura' vacía el número.
  - Si solo se informa el número, se conserva la obra social actual.
- **Alta:** el DNI no puede estar registrado. Tampoco puede ser el de un cliente dado de baja: con
  la baja lógica el documento sigue existiendo y el DNI no se reutiliza.
- **Modificación y baja:** el cliente debe existir y estar activo.

**Consistencia.** Cada operación escribe un solo documento, y en MongoDB una escritura sobre un
documento es atómica. Por eso, a diferencia de q14, no hace falta una transacción.

- **DNI único en dos niveles.**
  - Antes de insertar se busca el DNI, para dar un mensaje claro que indica a qué cliente
    pertenece.
  - El índice único `{dni}` es la garantía real. Si dos altas con el mismo DNI pasan la consulta
    a la vez, la segunda choca contra el índice (`DuplicateKeyError`) y se rechaza igual. El test
    `test_dos_altas_simultaneas_con_el_mismo_dni` lo verifica.
- **Id nuevo.** Sale del contador atómico `contadores.clientes` (C019, C020, …).
- **Modificación y baja** usan `find_one_and_update` con el filtro `{_id, activo: true}`. Si otra
  operación dio de baja al cliente entre la lectura y la escritura, no se modifica nada.
- **Baja lógica.** Solo cambia `activo` a `false`. Las ventas y recetas del cliente lo siguen
  referenciando, y q03, q10 y q12 lo siguen mostrando. q14 ya no le registra ventas.

```python
# Alta
if db.clientes.find_one({"dni": dni}) is not None:
    raise ErrorValidacion(f"ya existe un cliente con DNI {dni} …")
cliente = {"_id": reservar_ids(db, "clientes")[0], …, "activo": True}
try:
    db.clientes.insert_one(cliente)
except DuplicateKeyError:                      # alta simultánea con el mismo DNI
    raise ErrorValidacion(f"ya existe un cliente con DNI {dni} …")
```

```javascript
// Modificación de contacto y cobertura (solo los campos informados)
db.clientes.findOneAndUpdate(
  { _id: "C001", activo: true },
  { $set: { "contacto.email": "lucia.nueva@gmail.com", "contacto.telefono": "1140001111" } },
  { returnDocument: "after" })

// Baja lógica
db.clientes.findOneAndUpdate({ _id: "C014", activo: true }, { $set: { activo: false } },
                             { returnDocument: "after" })
```

**Estado antes y después:**

```bash
make consulta Q=q13 ARGS="alta --nombre Ana --apellido Paz --dni 40111222 --email ana.p@gmail.com --telefono 3415001122 --ciudad Rosario --provincia 'Santa Fe' --obra-social OSDE --nro-afiliado OS-777001"
make consulta Q=q13 ARGS="modificar C001 --email lucia.nueva@gmail.com --telefono 1140001111"
make consulta Q=q13 ARGS="modificar C011 --obra-social IOMA --nro-afiliado IO-778899"
make consulta Q=q13 ARGS="modificar C001 --obra-social 'Sin cobertura'"
make consulta Q=q13 ARGS="baja C014"
```

| Operación | Antes | Después |
|---|---|---|
| Alta | 18 clientes; no hay ninguno con DNI 40111222 | 19 clientes; nuevo **C019** Ana Paz · OSDE OS-777001 · activo |
| Modificar contacto de C001 | lucia.f@gmail.com · 1145112233 | lucia.nueva@gmail.com · 1140001111 (cobertura sin cambios) |
| Modificar cobertura de C011 | Sin cobertura · afiliado vacío | IOMA · IO-778899 |
| C001 pasa a 'Sin cobertura' | OSDE · OS-310045 | Sin cobertura · afiliado vacío |
| Baja de C014 | activo = true | activo = **false**; el documento y el resto de sus datos se conservan |

Documento devuelto por el alta:

```json
{ "antes": null,
  "despues": { "_id": "C019", "nombre": "Ana", "apellido": "Paz", "dni": "40111222",
               "contacto": { "email": "ana.p@gmail.com", "telefono": "3415001122" },
               "domicilio": { "ciudad": "Rosario", "provincia": "Santa Fe" },
               "cobertura": { "obra_social": "OSDE", "nro_afiliado": "OS-777001" },
               "activo": true } }
```

Después de la baja, C014 sigue apareciendo en q12 con `activo: false`, y una venta a su nombre se
rechaza:
`make consulta Q=q14 ARGS="--cliente C014 --farmaceutico F008 --item PRD014:1 --medio-pago Efectivo"`
→ `RECHAZADO: el cliente C014 está dado de baja`.

**Rechazos por validación.** Ninguno modifica datos:

| Comando (`ARGS`) | Resultado |
|---|---|
| `alta … --dni 31245678 …` | `ya existe un cliente con DNI 31245678 (cliente C001)` |
| `alta … --dni 25678901 …` | `ya existe un cliente con DNI 25678901 (cliente C008, dado de baja)` |
| `modificar C001 --obra-social PAMI` | `falta el número de afiliado de PAMI` |
| `modificar C015 --email x@gmail.com` | `el cliente C015 está dado de baja` |
| `baja C014` (por segunda vez) | `el cliente C014 está dado de baja` |

### q14 — Registro de una nueva venta Completada

- **Parámetros:** `--cliente`, `--farmaceutico`, `--item PRODUCTO:CANTIDAD` (se puede repetir),
  `--medio-pago` y `--receta` (opcional).
- **Motores:** MongoDB (transacción) + Redis (actualización de vistas después del commit).

**Validaciones**, todas dentro de la transacción. Cualquiera que falle rechaza la venta:

- el cliente existe y está activo;
- el farmacéutico existe y está activo, y su sucursal es una Farmacia habilitada;
- todos los productos existen y están activos;
- si hay productos bajo receta: la receta es obligatoria, existe, es del mismo cliente, está
  Vigente y le quedan dispensas;
- si se informa una receta, la venta debe incluir algún producto bajo receta;
- el stock vigente de la sucursal alcanza (lo comprueba q15).

**Efectos:**

- **Venta:** se crea con fecha de hoy y estado Completada. El precio de cada ítem es el de lista
  vigente y el total es la suma de los ítems.
- **Receta:** suma una dispensa. Si llega a las autorizadas pasa a Completada y
  `proxima_dispensa` queda vacía; si no, `proxima_dispensa` es hoy + 30 días.
- **Stock:** se descuenta con q15 dentro de **la misma transacción**.
- **Redis:** después del commit, `ZINCRBY` actualiza el ranking de productos y los ingresos del
  mes.

```python
with client.start_session() as session:
    resultado = session.with_transaction(lambda s: _registrar(db, s, …))
    #   _registrar: valida → inserta venta → actualiza receta (update condicional)
    #               → descontar_stock(id_venta, session=s)   # q15, misma transacción
vistas.aplicar_venta(resultado["venta"])                       # Redis, después del commit
```

El ejemplo con el antes y el después está en la sección 7.3.

### q15 — Actualización masiva del stock (FEFO)

- **Parámetro:** `id_venta`.
- **Motor:** MongoDB (transacción). Si la llama q14, usa su misma sesión; si no, abre una propia.

**Algoritmo:**

1. Valida que la venta exista, esté Completada y no tenga ya el stock descontado
   (`stock_aplicado`).
2. Lee los lotes **vigentes** (`vencimiento ≥ hoy`, `unidades > 0`) de la sucursal de la venta
   para los productos del detalle.
3. Arma el plan completo en memoria: para cada producto recorre los lotes del que vence antes al
   que vence después (FEFO). Si algún producto no alcanza, rechaza **antes de escribir nada**.
4. Aplica cada paso con una actualización condicional que nunca deja stock negativo:

   ```javascript
   db.stock_lotes.updateOne({ _id: LOTE, unidades: { $gte: N } }, { $inc: { unidades: -N } })
   ```

   Si alguna no modifica el documento (otra operación consumió el lote en el medio), lanza
   `StockInsuficiente` y la transacción aborta.
5. Marca la venta con `stock_aplicado = true` y guarda `lotes_consumidos`.

**Ejemplos de rechazo:**

- `ARGS="V011"` → `RECHAZADO: la venta V011 está Pendiente: solo las Completadas descuentan stock`
- `ARGS="V003"` → `RECHAZADO: la venta V003 ya tiene el stock descontado`
- `ARGS="V999"` → `RECHAZADO: la venta V999 no existe`

Después de `make cargar` todas las ventas Completadas ya tienen el stock aplicado. Por eso,
desde la terminal, el camino exitoso de q15 se ve a través de q14 (sección 7.3).

---

## 7. Consistencia e integridad en q14 y q15

### 7.1 Estrategia: una única transacción multi-documento

El enunciado pide que, si falla el descuento de stock, no quede ni la venta ni la receta
modificadas. Se usa una **transacción multi-documento de MongoDB**: es posible porque el motor
corre como replica set (`rs0`), y se eligió por sobre la compensación manual.

La transacción abarca:

- el insert de la venta;
- el update de la receta;
- los updates de los lotes;
- la marca `stock_aplicado` en la venta.

Cualquier `ErrorValidacion` lanzado dentro de la función aborta la transacción completa. Eso
incluye `StockInsuficiente`, aunque se detecte en el último ítem.

Se usa `session.with_transaction`, que **reintenta automáticamente** ante errores transitorios.
El caso típico es un conflicto de escritura (*write conflict*): dos ventas simultáneas que
modifican el mismo lote o la misma receta. En el reintento se vuelven a leer los datos
actualizados y se vuelve a validar. El test
`test_dos_ventas_simultaneas_no_dejan_stock_negativo` lo verifica.

### 7.2 Otras garantías

| Riesgo | Cómo se evita |
|---|---|
| Stock negativo | Update condicional `unidades ≥ n` + validador `$jsonSchema` (`unidades` mínimo 0) |
| Dispensar dos veces la misma receta | El update de la receta filtra por el `estado` y las `dispensas_realizadas` leídos; si no coincide, rechaza |
| Descontar dos veces la misma venta | `stock_aplicado` se verifica y se marca dentro de la transacción |
| Ids duplicados en altas simultáneas | `$inc` atómico sobre la colección `contadores`. Se hace **fuera** de la transacción para que las ventas concurrentes no choquen por el contador; un rechazo puede dejar un número sin usar, sin otro efecto |
| Redis desincronizado | Redis se actualiza **después** del commit. Si falla, la venta igual queda registrada (`vistas_actualizadas: false`) y las vistas se corrigen en la próxima reconstrucción. Es consistencia eventual, aceptable porque Redis solo guarda datos derivados |

### 7.3 Estado antes y después

**Caso exitoso:**

```bash
make consulta Q=q14 ARGS='--cliente C017 --farmaceutico F008 --receta RC016 --item PRD015:5 --medio-pago "Obra social"'
```

| | Antes | Después |
|---|---|---|
| Ventas | 34 | 35 (nueva V035) |
| Receta RC016 | Vigente · 2 de 3 dispensas · próxima 2026-12-13 | **Completada** · 3 de 3 · próxima vacía |
| L019 (PRD015, S006, vence 2026-11-10) | 30 | 30 (**vencido: se saltea**) |
| L020 (PRD015, S006, vence 2026-12-03) | 3 | 0 (se consume primero, FEFO) |
| L021 (PRD015, S006, vence 2027-07-31) | 120 | 118 |

Venta registrada:

```json
{ "_id": "V035", "id_sucursal": "S006", "fecha": "2026-11-13", "tipo": "Con receta",
  "total": 21500, "estado": "Completada",
  "items": [ { "id_detalle": "D042", "id_producto": "PRD015", "cantidad": 5, "precio_unit": 4300 } ],
  "stock_aplicado": true,
  "lotes_consumidos": [ { "id_lote": "L020", "id_producto": "PRD015", "unidades": 3 },
                        { "id_lote": "L021", "id_producto": "PRD015", "unidades": 2 } ] }
```

**Rechazo con rollback.** El primer ítem tiene stock, pero el segundo no:

```bash
make consulta Q=q14 ARGS="--cliente C011 --farmaceutico F008 --receta RC015 --item PRD018:2 --item PRD019:1 --medio-pago Débito"
RECHAZADO: stock vigente insuficiente: PRD019 (pedido 1, disponible 0)
```

| | Antes | Después |
|---|---|---|
| Ventas | 35 | 35 (no se creó ninguna) |
| Receta RC015 | Vigente · 0 de 1 | Vigente · 0 de 1 (sin cambios) |
| L022 (PRD018, S006) | 49 | 49 (sin cambios) |

**Otros rechazos por validación** (ninguno modifica datos):

| Comando (`ARGS`) | Resultado |
|---|---|
| `--cliente C009 --farmaceutico F008 --receta RC012 --item PRD015:1 …` | `la receta RC012 está Vencida, no Vigente` |
| `--cliente C001 --farmaceutico F001 --receta RC006 --item PRD007:1 …` | `la receta RC006 no pertenece al cliente C001` |
| `--cliente C015 --farmaceutico F008 --item PRD014:1 …` | `el cliente C015 está dado de baja` |
| `--cliente C001 --farmaceutico F004 --item PRD001:1 …` | `el farmacéutico F004 no está activo` |
| `--cliente C001 --farmaceutico F007 --item PRD001:1 …` | `la sucursal S005 no es una Farmacia: no registra ventas` |
| `--cliente C018 --farmaceutico F008 --item PRD023:1 …` | `productos discontinuados: PRD023` |
| `--cliente C018 --farmaceutico F008 --item PRD018:1 …` | `se requiere receta para: PRD018` |

`make demo` reproduce un antes y después equivalente sobre los datos originales.

---

## 8. Pruebas

`make test` corre 134 tests (pytest) contra el MongoDB y el Redis reales del entorno, en una base
(`farmared_test`) y una db de Redis (15) separadas, así no tocan los datos de trabajo. Cubren:

- la carga: idempotencia, rechazo de CSV inválidos y desplazamiento de fechas;
- los resultados de las consultas de lectura contra valores calculados a mano;
- q13 (`tests/test_clientes.py`, 33 tests): alta, rechazo por DNI duplicado (también el de un
  cliente dado de baja), dos altas simultáneas con el mismo DNI, modificación de contacto y de
  cobertura, baja lógica y rechazos por datos inválidos, siempre verificando que un rechazo no
  modifique nada;
- los casos válidos y los rechazos de q14 y q15;
- la atomicidad ante falta de stock;
- la concurrencia de dos ventas sobre el mismo lote;
- los registros adicionales reales de `data/extra/`: que haya al menos 10 por colección y que
  cada caso borde de la sección 5.1 se cumpla. Se prueban dos fechas de carga, la de referencia
  y una casi cuatro meses posterior, para verificar que el desplazamiento de fechas los conserva.

---

## 9. Limitaciones, alternativas evaluadas y conclusiones

### 9.1 Limitaciones

- **Replica set de un nodo.** Alcanza para tener transacciones, pero no da alta disponibilidad.
  En producción harían falta al menos tres nodos.
- **Consistencia eventual de Redis.** Si falla Redis justo después del commit, q01, q07 y q11
  pueden quedar desactualizadas hasta la próxima reconstrucción (`make reconstruir-vistas` o una
  carga).
- **La carga reinicia las bases.** Es idempotente porque reconstruye el estado inicial. Por eso
  borra las ventas y altas registradas después.
- **Desplazamiento de fechas por días.** Preserva las distancias en días, no los meses
  calendario. Las ventas que q11 necesita en el mes actual se fijaron en la fecha de referencia
  para que siempre caigan en el mes en curso.
- **Integridad referencial en la aplicación.** Una escritura hecha por fuera de los servicios,
  por ejemplo desde `mongosh`, puede dejar referencias rotas. Los validadores `$jsonSchema` solo
  controlan la forma de cada documento.

### 9.2 Alternativas evaluadas

| Alternativa | Por qué no se eligió |
|---|---|
| Embeber los lotes dentro del producto | Cada venta reescribiría el documento completo del producto. Aumentan los conflictos de escritura entre sucursales y el documento crece sin límite. |
| Colección separada para `detalle_ventas` | Toda lectura de una venta necesitaría un `$lookup`, y el alta dejaría de ser una sola escritura atómica. |
| Compensación manual en lugar de transacción para q14 + q15 | Hay que escribir y probar el deshacer de cada paso y, si el proceso cae a mitad de camino, quedan estados intermedios visibles. La transacción da atomicidad y aislamiento sin código extra. |
| Redis como fuente de verdad del stock (`DECRBY` atómico) | Sería rápido, pero el stock debe persistir y combinarse atómicamente con la venta y la receta, que viven en MongoDB. Una transacción entre dos motores no es posible. |
| Calcular q07 y q11 con agregaciones de MongoDB | Funciona, pero recorre todas las ventas en cada consulta. Con los ZSET de Redis el costo es O(log n) y el ranking se actualiza en cada venta. |
| Neo4j para el historial cliente–receta–venta–producto | Los recorridos que pide el enunciado tienen profundidad fija y se resuelven con `$lookup` / `$unionWith`. Sumar un tercer motor agregaba complejidad sin una ganancia clara. |

### 9.3 Conclusiones

- **MongoDB** concentra los datos de negocio: el modelo de documentos encaja con las ventas y sus
  ítems, el *aggregation framework* resuelve las consultas que cruzan entidades y las
  transacciones multi-documento cubren el requisito más exigente del enunciado (q14 + q15
  atómicos).
- **Redis** cumple el rol de modelo de lectura: sirve el catálogo y los reportes agregados desde
  memoria y, como sus datos se pueden reconstruir siempre, no compromete la consistencia del
  sistema.
- Separar **fuente de verdad** y **vistas derivadas** permitió aprovechar cada motor en lo que
  mejor hace. La integridad que ningún motor garantiza se resolvió con validaciones explícitas en
  la carga y en los servicios.

---

## Anexo — Cómo ejecutar

```bash
# En GitHub Codespaces: Code → Codespaces → Create codespace on main
make verificar                          # Mongo (replica set + transacción) y Redis
make cargar                             # CSV originales + adicionales
make consulta                           # lista las consultas disponibles
make consulta Q=q05                     # ejecuta una consulta
make consulta Q=q03 ARGS="C009"         # consulta con parámetro
make consulta Q=q13 ARGS="baja C014"    # servicio con subcomando (alta / modificar / baja)
make demo                               # antes / después de q14 + q15
make test                               # tests
```
