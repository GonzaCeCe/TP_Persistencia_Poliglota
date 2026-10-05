# Guía de agregaciones de MongoDB para la defensa

Material de estudio. Explica cada reporte y cada consulta agregada del sistema: qué pregunta responde, el
pipeline exacto (en `app/repositorios/documental.py`), su equivalente en SQL y por qué está hecho así.

## Por qué hay aggregation pipeline

La cátedra plantea que procesar los datos del lado del cliente es el último recurso: traer todos los envíos
a Python para contarlos movería datos de más por la red. Por eso los agrupamientos se hacen en la base, pero
**solo con lo mínimo**:

| Etapa de MongoDB | Equivalente en SQL | Qué hace |
|---|---|---|
| `$match` | `WHERE` | Filtra documentos. Puede usar índices, igual que un `WHERE`. |
| `$group` | `GROUP BY` | Agrupa por la clave `_id` y calcula acumuladores por grupo. |
| `$sort` | `ORDER BY` | Ordena (`1` ascendente, `-1` descendente). |
| `$unwind` | Desarmar un arreglo en filas (como un `JOIN` contra la tabla de detalle) | Convierte un documento con un arreglo de N elementos en N documentos, uno por elemento. |
| `$limit` | `LIMIT` | Corta la cantidad de resultados. |

| Acumulador | SQL |
|---|---|
| `{$sum: 1}` | `COUNT(*)` |
| `{$sum: "$campo"}` | `SUM(campo)` |
| `$avg`, `$min`, `$max` | `AVG`, `MIN`, `MAX` |
| `$first` | Un valor de la primera fila del grupo (útil para traer el nombre junto al id) |

**No se usa** `$project` con cálculos, `$dateDiff`, `$dateToString`, `$cond`, `$expr`, `$lookup` ni `$facet`.
Lo que antes se calculaba con esos operadores ahora sale de dos lugares:

- **Campos que se guardan al entregar el envío.** Cuando un envío pasa a ENTREGADO, `dominio/reglas.py`
  (`metricas_de_entrega`, función pura con tests) calcula tres campos y se guardan en el mismo `updateOne`
  que cambia el estado:
  - `dias_entrega`: días con decimales entre `fecha_creacion` y `fecha_entrega_real`;
  - `demorado`: 1 si `fecha_entrega_real > fecha_entrega_estimada`, si no 0;
  - `mes_entrega`: texto `AAAA-MM`.

  Así las consultas solo suman, promedian o agrupan campos que ya existen.
- **Python, sobre el resultado agrupado.** Ahí se hace lo que es pura presentación: renombrar `_id`,
  redondear y calcular porcentajes. Son pocas filas, ya agrupadas en la base.

Todos los reportes aceptan un rango de fechas (`desde`, `hasta`) y, si el usuario es de un cliente, se
filtran por ese cliente. En el código eso es el `$match` inicial, que arma `_filtro_envios`:

```js
{ fecha_creacion: { $gte: desde, $lt: hasta }, "cliente.id": <cliente del usuario> }
```

En los ejemplos de abajo ese filtro aparece como `<filtro>`.

---

## 1. Envíos por país de destino

**Pregunta:** ¿cuántos envíos van a cada país?

```js
db.envios.aggregate([
  { $match: <filtro> },
  { $group: { _id: "$destino.pais", cantidad: { $sum: 1 } } },
  { $sort: { cantidad: -1, _id: 1 } }
])
```

```sql
SELECT destino_pais AS pais, COUNT(*) AS cantidad
FROM envios WHERE <filtro>
GROUP BY destino_pais ORDER BY cantidad DESC, pais;
```

Agrupa por el país del subdocumento `destino` y cuenta. En Python, `_id` se renombra a `pais`.

## 2. Envíos por estado

**Pregunta:** ¿cuántos envíos hay en cada estado (CREADO, EN_TRANSITO, ENTREGADO…)?

```js
db.envios.aggregate([
  { $match: <filtro> },
  { $group: { _id: "$estado", cantidad: { $sum: 1 } } },
  { $sort: { cantidad: -1, _id: 1 } }
])
```

```sql
SELECT estado, COUNT(*) AS cantidad FROM envios WHERE <filtro> GROUP BY estado ORDER BY cantidad DESC, estado;
```

Igual que el anterior, agrupando por `estado`.

## 3. Envíos por cliente

**Pregunta:** ¿cuántos envíos tiene cada cliente?

```js
db.envios.aggregate([
  { $match: <filtro> },
  { $group: { _id: "$cliente.id", cantidad: { $sum: 1 }, cliente: { $first: "$cliente.razon_social" } } },
  { $sort: { cantidad: -1, _id: 1 } }
])
```

```sql
SELECT cliente_id, MIN(cliente_razon_social) AS cliente, COUNT(*) AS cantidad
FROM envios WHERE <filtro> GROUP BY cliente_id ORDER BY cantidad DESC, cliente_id;
```

Se agrupa por el **id** del cliente (no por el nombre, que podría repetirse). `$first` trae la razón social
del snapshot para mostrarla.

## 4. Envíos demorados

**Pregunta:** ¿qué envíos están o estuvieron demorados?

No es una agregación: es un `find` con `$or`.

```js
db.envios.find({
  <filtro>,
  $or: [
    { estado: { $nin: ["ENTREGADO", "CANCELADO"] }, fecha_entrega_estimada: { $lt: ahora } },
    { demorado: 1 }
  ]
}).sort({ _id: 1 })
```

```sql
SELECT * FROM envios
WHERE <filtro>
  AND ((estado NOT IN ('ENTREGADO','CANCELADO') AND fecha_entrega_estimada < :ahora) OR demorado = 1)
ORDER BY id;
```

Hay dos casos:
- **En curso y vencido:** se compara la fecha estimada con "ahora".
- **Entregado tarde:** basta con `demorado: 1`, que se calculó al entregar.

Los días de demora de cada fila se calculan en Python (`dias_entre`). La primera condición usa el índice
`{estado, fecha_entrega_estimada}`.

## 5. Incidentes abiertos

**Pregunta:** ¿qué incidentes siguen abiertos?

```js
db.incidentes.find({ estado: "ABIERTO", fecha: { $gte: desde, $lt: hasta } }).sort({ fecha: 1 })
```

```sql
SELECT * FROM incidentes WHERE estado = 'ABIERTO' AND fecha >= :desde AND fecha < :hasta ORDER BY fecha;
```

Filtro simple que usa el índice `{estado, fecha}`. Para un usuario de cliente se agrega
`envio_id: { $in: [ids de sus envíos] }`.

## 6. Tiempos máximo, mínimo y promedio de envío por cliente

**Pregunta:** ¿cuánto tardan los envíos de cada cliente?

```js
db.envios.aggregate([
  { $match: { <filtro sobre fecha_entrega_real>, estado: "ENTREGADO" } },
  { $group: {
      _id: "$cliente.id",
      cliente: { $first: "$cliente.razon_social" },
      entregados: { $sum: 1 },
      dias_maximo: { $max: "$dias_entrega" },
      dias_minimo: { $min: "$dias_entrega" },
      dias_promedio: { $avg: "$dias_entrega" } } },
  { $sort: { _id: 1 } }
])
```

```sql
SELECT cliente_id, COUNT(*) AS entregados,
       MAX(dias_entrega), MIN(dias_entrega), AVG(dias_entrega)
FROM envios WHERE estado = 'ENTREGADO' AND <filtro>
GROUP BY cliente_id ORDER BY cliente_id;
```

Solo cuentan los entregados. `dias_entrega` ya está guardado en cada envío, así que no hace falta restar
fechas en la consulta. El redondeo a 2 decimales se hace en Python.

## 7. Tiempo promedio de entrega (global)

**Pregunta:** ¿cuánto tarda en promedio un envío?

```js
db.envios.aggregate([
  { $match: { <filtro sobre fecha_entrega_real>, estado: "ENTREGADO" } },
  { $group: { _id: null, entregados: { $sum: 1 }, dias_promedio: { $avg: "$dias_entrega" } } }
])
```

```sql
SELECT COUNT(*) AS entregados, AVG(dias_entrega) FROM envios WHERE estado = 'ENTREGADO' AND <filtro>;
```

`_id: null` arma **un solo grupo** con todos los documentos: es un agregado sin `GROUP BY`.

## 8 a 10. Promedio de incidentes por país, estado o cliente

**Pregunta:** ¿cuántos incidentes tiene en promedio un envío según su país de destino, su estado o su
cliente?

```js
db.envios.aggregate([
  { $match: <filtro> },
  { $group: {
      _id: "$destino.pais",              // o "$estado", o "$cliente.id"
      envios: { $sum: 1 },
      incidentes: { $sum: "$cantidad_incidentes" },
      promedio: { $avg: "$cantidad_incidentes" } } },
  { $sort: { promedio: -1, _id: 1 } }
])
```

```sql
SELECT destino_pais, COUNT(*) AS envios, SUM(cantidad_incidentes), AVG(cantidad_incidentes) AS promedio
FROM envios WHERE <filtro> GROUP BY destino_pais ORDER BY promedio DESC;
```

Usa `cantidad_incidentes`, el contador que se mantiene en cada envío con `$inc` y que el control de
integridad reconcilia contra la colección `incidentes`. Por cliente se agrega
`cliente: { $first: "$cliente.razon_social" }`.

## 11. Costos por tipo de transporte

**Pregunta:** ¿cuánto se gastó por medio de transporte (terrestre, marítimo, aéreo)?

```js
db.envios.aggregate([
  { $match: <filtro> },
  { $unwind: "$tramos" },
  { $group: {
      _id: "$tramos.medio",
      tramos: { $sum: 1 },
      costo_total: { $sum: "$tramos.costo" },
      costo_promedio: { $avg: "$tramos.costo" } } },
  { $sort: { costo_total: -1 } }
])
```

```sql
SELECT t.medio, COUNT(*) AS tramos, SUM(t.costo), AVG(t.costo)
FROM envios e JOIN tramos t ON t.envio_id = e.id
WHERE <filtro> GROUP BY t.medio ORDER BY SUM(t.costo) DESC;
```

Los tramos están **embebidos** en el envío. `$unwind` los "desarma": un envío con 2 tramos se convierte en 2
documentos, uno por tramo, que después se agrupan por `medio`. Es lo que en SQL sería el `JOIN` con la tabla
de tramos.

## 12. Ranking de rutas con más incidentes

**Pregunta:** ¿qué rutas (origen-destino) tienen más incidentes?

Se hacen dos agrupaciones iguales, una con todos los incidentes y otra solo con los abiertos, y Python las
combina:

```js
// total por ruta
db.incidentes.aggregate([
  { $match: { fecha: { $gte: desde, $lt: hasta } } },
  { $group: { _id: "$ruta", incidentes: { $sum: 1 } } },
  { $sort: { incidentes: -1, _id: 1 } }
])
// abiertos por ruta: lo mismo con { $match: { ..., estado: "ABIERTO" } }
```

```sql
SELECT ruta, COUNT(*) AS incidentes FROM incidentes WHERE <fechas> GROUP BY ruta ORDER BY incidentes DESC;
SELECT ruta, COUNT(*) AS abiertos   FROM incidentes WHERE <fechas> AND estado = 'ABIERTO' GROUP BY ruta;
```

`ruta` (por ejemplo `ARROS-BRSSZ`) se guarda en cada incidente al crearlo, así se agrupa sin cruzar con
`envios`. Contar "abiertos" en la misma pasada requeriría `$cond`; con dos consultas simples queda igual de
claro.

## 13. Ranking de clientes por volumen transportado

**Pregunta:** ¿qué clientes mueven más carga?

```js
db.envios.aggregate([
  { $match: { <filtro>, estado: { $ne: "CANCELADO" } } },
  { $group: {
      _id: "$cliente.id",
      cliente: { $first: "$cliente.razon_social" },
      envios: { $sum: 1 },
      volumen_m3: { $sum: "$volumen_m3" },
      peso_kg: { $sum: "$peso_kg" } } },
  { $sort: { volumen_m3: -1, peso_kg: -1 } }
])
```

```sql
SELECT cliente_id, COUNT(*), SUM(volumen_m3), SUM(peso_kg)
FROM envios WHERE <filtro> AND estado <> 'CANCELADO'
GROUP BY cliente_id ORDER BY SUM(volumen_m3) DESC, SUM(peso_kg) DESC;
```

Suma volumen y peso por cliente, excluyendo los cancelados (no transportaron nada).

## 14. Análisis histórico de desempeño

**Pregunta:** mes a mes, ¿qué porcentaje de envíos se entregó a tiempo?

```js
db.envios.aggregate([
  { $match: { <filtro sobre fecha_entrega_real>, estado: "ENTREGADO" } },
  { $group: { _id: "$mes_entrega", entregados: { $sum: 1 }, demorados: { $sum: "$demorado" } } },
  { $sort: { _id: 1 } }
])
```

```sql
SELECT mes_entrega, COUNT(*) AS entregados, SUM(demorado) AS demorados
FROM envios WHERE estado = 'ENTREGADO' AND <filtro>
GROUP BY mes_entrega ORDER BY mes_entrega;
```

Como `demorado` vale 0 o 1, sumarlo da la cantidad de demorados. `mes_entrega` ya viene como `AAAA-MM`, así
que no hace falta formatear fechas en la consulta. En Python:
`a_tiempo = entregados - demorados` y `porcentaje = a_tiempo / entregados × 100`.

## 15. Red de relaciones (Neo4j)

Este reporte no usa MongoDB: es un recorrido en Cypher sobre el grafo (ver `RED_CLIENTES_OPERADORES` en
`app/repositorios/grafo.py`):

```cypher
MATCH (c:Cliente)-[:SOLICITO]->(e:Envio)-[:INCLUYE]->(:Tramo)-[:OPERADO_POR]->(op:Operador)
RETURN c.id, c.razon_social, op.id, op.razon_social, collect(DISTINCT e.id) AS envios
```

En SQL serían cuatro tablas unidas con `JOIN`. En el grafo es un patrón que sigue relaciones.

---

## Otras agregaciones del sistema

### Tasa de demora por ruta (predicción diaria)

```js
db.envios.aggregate([
  { $match: { estado: "ENTREGADO" } },
  { $group: {
      _id: { origen: "$origen.codigo", destino: "$destino.codigo" },
      entregados: { $sum: 1 },
      tasa_demora: { $avg: "$demorado" } } }
])
```

```sql
SELECT origen_codigo, destino_codigo, COUNT(*), AVG(demorado) AS tasa_demora
FROM envios WHERE estado = 'ENTREGADO' GROUP BY origen_codigo, destino_codigo;
```

El **promedio de un campo 0/1 es una proporción**: si 1 de 4 envíos llegó tarde, `AVG(demorado) = 0.25`. La
clave de grupo es un objeto con dos campos (como `GROUP BY` de dos columnas). El texto `"ARROS-BRSSZ"` se
arma en Python.

### Incidentes abiertos por envío y alertas abiertas por contenedor (riesgo operativo)

```js
db.incidentes.aggregate([{ $match: { estado: "ABIERTO" } }, { $group: { _id: "$envio_id", cantidad: { $sum: 1 } } }])
db.alertas.aggregate([{ $match: { estado: "ABIERTA", contenedor_id: { $ne: null } } },
                      { $group: { _id: "$contenedor_id", cantidad: { $sum: 1 } } }])
```

```sql
SELECT envio_id, COUNT(*) FROM incidentes WHERE estado = 'ABIERTO' GROUP BY envio_id;
```

Conteos por clave para calcular el riesgo operativo de cada envío activo.

### Mis conversaciones (mensajería)

```js
db.mensajes.aggregate([
  { $match: { participantes: <usuario> } },
  { $sort: { fecha_hora: -1 } },
  { $group: {
      _id: "$conversacion_id",
      mensajes: { $sum: 1 },
      fecha_hora: { $first: "$fecha_hora" },
      contenido: { $first: "$contenido" },
      participantes: { $first: "$participantes" } } },
  { $sort: { fecha_hora: -1 } }
])
```

Primero se ordena por fecha descendente. Así, `$first` dentro de cada grupo toma el **último mensaje** de
cada conversación: es el patrón "último registro por grupo".
