// Creacion del modelo documental. Requiere el replica set iniciado. Idempotente.
// Uso: docker compose exec mongo mongosh --quiet --port <MONGO_PORT> <MONGO_DB> --file /scripts/mongo_init.js
// lecturas es time series: MongoDB 7 no admite validator en ese tipo de coleccion (se valida en la aplicacion).

const ENTERO = { bsonType: ['int', 'long'] };
const ENTERO_O_NULO = { bsonType: ['int', 'long', 'null'] };
const NUMERO_O_NULO = { bsonType: ['number', 'null'] };
const FECHA = { bsonType: 'date' };
const FECHA_O_NULO = { bsonType: ['date', 'null'] };
const TEXTO = { bsonType: 'string', minLength: 1 };
const PAIS = { bsonType: 'string', pattern: '^[A-Z]{2}$' };
const FRACCION = { bsonType: 'number', minimum: 0, maximum: 1 };

const UBICACION = {
  bsonType: 'object',
  required: ['codigo', 'ciudad', 'pais'],
  properties: {
    codigo: { bsonType: 'string', pattern: '^[A-Z]{2}[A-Z0-9]{3}$' },
    ciudad: TEXTO,
    pais: PAIS
  }
};

const TRAMO = {
  bsonType: 'object',
  required: ['id', 'orden', 'medio', 'origen', 'destino', 'operador', 'vehiculo',
             'fecha_salida', 'fecha_llegada_estimada', 'costo'],
  properties: {
    id: { bsonType: 'string', pattern: '^\\d+-\\d+$' },
    orden: { bsonType: ['int', 'long'], minimum: 1 },
    medio: { enum: ['TERRESTRE', 'MARITIMO', 'AEREO'] },
    origen: UBICACION,
    destino: UBICACION,
    operador: { bsonType: 'object', required: ['id', 'razon_social'],
                properties: { id: ENTERO, razon_social: TEXTO } },
    vehiculo: { bsonType: 'object', required: ['id', 'identificacion'],
                properties: { id: ENTERO, identificacion: TEXTO } },
    fecha_salida: FECHA,
    fecha_llegada_estimada: FECHA,
    costo: { bsonType: 'number', minimum: 0 }
  }
};

const ESQUEMAS = {
  contadores: {
    bsonType: 'object',
    required: ['_id', 'valor'],
    properties: { _id: TEXTO, valor: ENTERO }
  },

  envios: {
    bsonType: 'object',
    required: ['_id', 'cliente', 'fecha_creacion', 'origen', 'destino', 'estado', 'prioridad',
               'peso_kg', 'volumen_m3', 'contenedores', 'tramos', 'fecha_entrega_estimada',
               'fecha_entrega_real', 'cantidad_incidentes', 'ultimo_evento', 'facturado',
               'factura_id', 'grafo_sincronizado'],
    properties: {
      _id: ENTERO,
      cliente: { bsonType: 'object', required: ['id', 'razon_social', 'pais'],
                 properties: { id: ENTERO, razon_social: TEXTO, pais: PAIS } },
      fecha_creacion: FECHA,
      origen: UBICACION,
      destino: UBICACION,
      estado: { enum: ['CREADO', 'EN_CARGA', 'EN_TRANSITO', 'EN_ADUANA', 'EN_DESCARGA',
                       'ENTREGADO', 'CANCELADO'] },
      prioridad: { enum: ['BAJA', 'MEDIA', 'ALTA'] },
      peso_kg: { bsonType: 'number', minimum: 0, exclusiveMinimum: true },
      volumen_m3: { bsonType: 'number', minimum: 0, exclusiveMinimum: true },
      contenedores: {
        bsonType: 'array', minItems: 1,
        items: { bsonType: 'object', required: ['id', 'codigo'],
                 properties: { id: ENTERO, codigo: { bsonType: 'string', pattern: '^[A-Z]{4}\\d{7}$' } } }
      },
      tramos: { bsonType: 'array', items: TRAMO },
      fecha_entrega_estimada: FECHA_O_NULO,
      fecha_entrega_real: FECHA_O_NULO,
      cantidad_incidentes: { bsonType: ['int', 'long'], minimum: 0 },
      ultimo_evento: {
        bsonType: ['object', 'null'],
        required: ['tipo', 'fecha_hora', 'ubicacion'],
        properties: { tipo: TEXTO, fecha_hora: FECHA, ubicacion: TEXTO }
      },
      facturado: { bsonType: 'bool' },
      factura_id: ENTERO_O_NULO,
      grafo_sincronizado: { bsonType: 'bool' }
    }
  },

  eventos: {
    bsonType: 'object',
    required: ['envio_id', 'contenedor_ids', 'fecha_hora', 'tipo', 'ubicacion', 'descripcion'],
    properties: {
      envio_id: ENTERO,
      contenedor_ids: { bsonType: 'array', items: ENTERO },
      fecha_hora: FECHA,
      tipo: { enum: ['CARGA_INICIADA', 'EN_TRANSITO', 'ADUANA', 'RETRASO', 'DESCARGA', 'ENTREGADO'] },
      ubicacion: TEXTO,
      descripcion: { bsonType: 'string' }
    }
  },

  incidentes: {
    bsonType: 'object',
    required: ['_id', 'envio_id', 'tramo_id', 'ruta', 'tipo', 'fecha', 'severidad', 'estado',
               'descripcion', 'fecha_cierre'],
    properties: {
      _id: ENTERO,
      envio_id: ENTERO,
      tramo_id: { bsonType: ['string', 'null'] },
      ruta: { bsonType: 'string', pattern: '^[A-Z0-9]{5}-[A-Z0-9]{5}$' },
      tipo: TEXTO,
      fecha: FECHA,
      severidad: { enum: ['BAJA', 'MEDIA', 'ALTA', 'CRITICA'] },
      estado: { enum: ['ABIERTO', 'CERRADO'] },
      descripcion: { bsonType: 'string' },
      fecha_cierre: FECHA_O_NULO
    }
  },

  alertas: {
    bsonType: 'object',
    required: ['_id', 'sensor_id', 'contenedor_id', 'envio_id', 'evento', 'tipo', 'fecha', 'estado',
               'valor', 'umbral', 'fecha_cierre'],
    properties: {
      _id: ENTERO,
      sensor_id: ENTERO,
      contenedor_id: ENTERO_O_NULO,
      envio_id: ENTERO_O_NULO,
      evento: { bsonType: 'object', required: ['origen', 'fecha_hora'],
                properties: { origen: { enum: ['LECTURA', 'PROCESO'] }, fecha_hora: FECHA } },
      tipo: { enum: ['TEMP_FUERA_RANGO', 'BATERIA_BAJA', 'SENSOR_INACTIVO'] },
      fecha: FECHA,
      estado: { enum: ['ABIERTA', 'CERRADA'] },
      valor: NUMERO_O_NULO,
      umbral: NUMERO_O_NULO,
      fecha_cierre: FECHA_O_NULO
    }
  },

  mensajes: {
    bsonType: 'object',
    required: ['conversacion_id', 'tipo', 'remitente_id', 'destinatario', 'fecha_hora', 'contenido'],
    properties: {
      conversacion_id: { bsonType: 'string', pattern: '^(u\\d+-u\\d+|g\\d+)$' },
      tipo: { enum: ['PRIVADO', 'GRUPAL'] },
      remitente_id: ENTERO,
      destinatario: { bsonType: 'object', required: ['tipo', 'id'],
                      properties: { tipo: { enum: ['USUARIO', 'GRUPO'] }, id: ENTERO } },
      participantes: { bsonType: 'array', minItems: 2, maxItems: 2, items: ENTERO },
      fecha_hora: FECHA,
      contenido: { bsonType: 'string', minLength: 1, maxLength: 2000 }
    }
  },

  grupos: {
    bsonType: 'object',
    required: ['_id', 'nombre', 'publico', 'integrantes'],
    properties: {
      _id: ENTERO,
      nombre: TEXTO,
      publico: { bsonType: 'bool' },
      integrantes: {
        bsonType: 'array', minItems: 2,
        items: { bsonType: 'object', required: ['usuario_id'], properties: { usuario_id: ENTERO } }
      }
    }
  },

  reportes: {
    bsonType: 'object',
    required: ['_id', 'usuario_id', 'tipo', 'parametros', 'formato', 'fecha_generacion', 'estado'],
    properties: {
      _id: ENTERO,
      usuario_id: ENTERO,
      tipo: TEXTO,
      parametros: { bsonType: 'object' },
      formato: { enum: ['JSON', 'CSV'] },
      fecha_generacion: FECHA,
      estado: { enum: ['PENDIENTE', 'GENERADO', 'ERROR'] },
      resultado: { bsonType: ['array', 'null'] }
    }
  },

  predicciones: {
    bsonType: 'object',
    required: ['_id', 'envio_id', 'dia', 'probabilidad_demora', 'riesgo_climatico', 'riesgo_operativo',
               'fecha_calculo', 'factores'],
    properties: {
      _id: ENTERO,
      envio_id: ENTERO,
      dia: { bsonType: 'string', pattern: '^\\d{4}-\\d{2}-\\d{2}$' },
      probabilidad_demora: FRACCION,
      riesgo_climatico: FRACCION,
      riesgo_operativo: FRACCION,
      fecha_calculo: FECHA,
      factores: { bsonType: 'object' }
    }
  }
};

function asegurarColeccion(nombre) {
  const validador = { $jsonSchema: ESQUEMAS[nombre] };
  if (db.getCollectionNames().includes(nombre)) {
    db.runCommand({ collMod: nombre, validator: validador, validationLevel: 'strict' });
  } else {
    db.createCollection(nombre, { validator: validador, validationLevel: 'strict', validationAction: 'error' });
  }
}

function asegurarLecturasTimeSeries() {
  const existente = db.getCollectionInfos({ name: 'lecturas' })[0];
  if (existente && existente.type !== 'timeseries') {
    throw new Error('La coleccion lecturas existe pero no es time series: eliminarla y volver a ejecutar');
  }
  if (!existente) {
    db.createCollection('lecturas', {
      timeseries: { timeField: 'fecha_hora', metaField: 'meta', granularity: 'minutes' }
    });
  }
}

Object.keys(ESQUEMAS).forEach(asegurarColeccion);
asegurarLecturasTimeSeries();

db.envios.createIndex({ 'cliente.id': 1, fecha_creacion: 1 });
db.envios.createIndex({ estado: 1, fecha_entrega_estimada: 1 });
db.envios.createIndex({ 'destino.pais': 1 });
db.envios.createIndex({ 'contenedores.id': 1, estado: 1 });
db.envios.createIndex({ estado: 1, fecha_entrega_real: 1 },
                      { name: 'pendientes_de_facturar', partialFilterExpression: { facturado: false } });
db.envios.createIndex({ grafo_sincronizado: 1 });

db.lecturas.createIndex({ 'meta.sensor_id': 1, fecha_hora: 1 });
db.lecturas.createIndex({ 'meta.contenedor_id': 1, fecha_hora: 1 });

db.eventos.createIndex({ envio_id: 1, fecha_hora: 1, tipo: 1 }, { unique: true });
db.eventos.createIndex({ contenedor_ids: 1, fecha_hora: 1 });

db.incidentes.createIndex({ estado: 1, fecha: 1 });
db.incidentes.createIndex({ envio_id: 1, estado: 1 });

db.alertas.createIndex({ sensor_id: 1, tipo: 1 },
                       { name: 'una_abierta_por_sensor_y_tipo', unique: true,
                         partialFilterExpression: { estado: 'ABIERTA' } });
db.alertas.createIndex({ contenedor_id: 1, estado: 1 });

db.mensajes.createIndex({ conversacion_id: 1, fecha_hora: 1 });
db.mensajes.createIndex({ participantes: 1, fecha_hora: 1 });

db.grupos.createIndex({ 'integrantes.usuario_id': 1 });

db.predicciones.createIndex({ envio_id: 1, dia: 1 }, { unique: true });

print('mongo_init: colecciones ' + db.getCollectionNames().filter(n => !n.startsWith('system.')).sort().join(', '));
