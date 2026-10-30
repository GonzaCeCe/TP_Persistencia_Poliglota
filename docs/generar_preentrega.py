from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

SALIDA = Path(__file__).resolve().parent / "Preentrega TP Persistencia Poliglota v2.docx"

AZUL_TITULOS = RGBColor(0x1F, 0x38, 0x64)
AZUL_SUBTITULOS = RGBColor(0x2F, 0x54, 0x96)
GRIS = RGBColor(0x59, 0x59, 0x59)
COLOR_SEPARADOR = "2F5496"
COLOR_BORDE_TABLA = "A6A6A6"
FONDO_ENCABEZADO = "D9E2F3"
FONDO_CODIGO = "F2F4F8"
FUENTE = "Arial"
FUENTE_CODIGO = "Courier New"
ANCHO_UTIL_CM = 16.0

PORTADA = {
    "titulo": "Trabajo Práctico IDD 2",
    "subtitulo": "Preentrega: Herramientas y justificaciones",
    "datos": [
        ("Materia", "Ingeniería de Datos II"),
        ("Docente", "Lic. Claudio Godio"),
        ("Grupo", "9"),
        ("Integrantes", "Travieso Bautista y Zeese Gonzalo"),
        ("Fecha", "[completar]"),
    ],
}

COLUMNAS_VENTAJAS = [("", 2.6), ("Característica", 5.2), ("Cómo afecta a la elección en este trabajo", 8.2)]

EJEMPLO_ENVIO = """{
  "_id": 2,
  "cliente": { "id": 2, "razon_social": "Bodega Los Andes SRL", "pais": "AR" },
  "fecha_creacion": ISODate("2026-04-06T10:00:00Z"),
  "origen":  { "codigo": "ARMDZ", "ciudad": "Mendoza", "pais": "AR" },
  "destino": { "codigo": "USNYC", "ciudad": "Nueva York", "pais": "US" },
  "estado": "ENTREGADO", "prioridad": "MEDIA",
  "peso_kg": 21000, "volumen_m3": 30,
  "contenedores": [ { "id": 2, "codigo": "TGHU7654321" } ],
  "tramos": [
    { "id": "2-1", "orden": 1, "medio": "TERRESTRE",
      "origen":  { "codigo": "ARMDZ", "ciudad": "Mendoza", "pais": "AR" },
      "destino": { "codigo": "ARBUE", "ciudad": "Buenos Aires", "pais": "AR" },
      "operador": { "id": 1, "razon_social": "Transportes del Sur SA" },
      "vehiculo": { "id": 1, "identificacion": "AE123CD" },
      "fecha_salida": ISODate("2026-04-07T06:00:00Z"),
      "fecha_llegada_estimada": ISODate("2026-04-09T18:00:00Z"),
      "costo": 1200 },
    { "id": "2-2", "orden": 2, "medio": "MARITIMO",
      "origen":  { "codigo": "ARBUE", "ciudad": "Buenos Aires", "pais": "AR" },
      "destino": { "codigo": "USNYC", "ciudad": "Nueva York", "pais": "US" },
      "operador": { "id": 2, "razon_social": "Naviera Atlántica SA" },
      "vehiculo": { "id": 2, "identificacion": "IMO9321483" },
      "fecha_salida": ISODate("2026-04-10T06:00:00Z"),
      "fecha_llegada_estimada": ISODate("2026-05-01T12:00:00Z"),
      "costo": 6800 }
  ],
  "fecha_entrega_estimada": ISODate("2026-05-01T12:00:00Z"),
  "fecha_entrega_real": ISODate("2026-05-04T11:00:00Z"),
  "cantidad_incidentes": 1,
  "ultimo_evento": { "tipo": "ENTREGADO", "fecha_hora": ISODate("2026-05-04T11:00:00Z"),
                     "ubicacion": "USNYC - Port Newark" },
  "facturado": true, "factura_id": 2, "grafo_sincronizado": true,
  "dias_entrega": 28.04, "demorado": 1, "mes_entrega": "2026-05"
}"""

SECCIONES = [
    {
        "titulo": "Objetivo",
        "bloques": [
            {"parrafo": (
                "El documento detalla las herramientas que se utilizan para desarrollar el trabajo práctico y la "
                "justificación de cada elección. La solución se implementa como una aplicación de consola que gestiona "
                "una plataforma de logística internacional con monitoreo de contenedores mediante sensores IoT, y "
                "accede a cuatro motores de bases de datos de distintos paradigmas.")},
        ],
    },
    {
        "titulo": "Lenguaje y entorno",
        "bloques": [
            {"tabla": ([("Herramienta", 4.5), ("Justificación", 11.5)], [
                ("Python 3.11",
                 "El enunciado permite Java o Python. Python cuenta con drivers oficiales para los cuatro motores y "
                 "permite resolver la aplicación con menos código."),
                ("Entorno virtual de Python",
                 "Aísla las dependencias del proyecto, declaradas con versiones fijas en un archivo de requisitos, "
                 "para que todos los integrantes trabajen con las mismas versiones."),
                ("Aplicación de consola",
                 "El enunciado solicita una aplicación, no una API REST ni una página web. El menú muestra a cada "
                 "usuario solo las opciones que corresponden a su rol."),
                ("Docker Compose",
                 "Permite levantar las cuatro bases, con versiones fijas de cada motor, mediante un único comando y de "
                 "la misma forma en el equipo de cada integrante y en la defensa."),
                ("Scripts de creación de bases de datos",
                 "Un script por motor (SQL para PostgreSQL, JavaScript para MongoDB y Cypher para Neo4j) crea tablas, "
                 "colecciones, índices y restricciones. Se ejecutan juntos con el inicializador de la aplicación o "
                 "por separado, y pueden repetirse sin errores."),
                ("Git", "Control de versiones del trabajo grupal."),
            ])},
        ],
    },
    {
        "titulo": "Bases de datos (persistencia políglota)",
        "bloques": [
            {"tabla": ([("Motor", 2.9), ("Paradigma", 2.4), ("Información que almacena", 5.0), ("Justificación", 5.7)], [
                ("PostgreSQL", "Relacional",
                 "Clientes, operadores logísticos, proveedores, usuarios, roles, historial de sesiones, contenedores, "
                 "sensores, vehículos, facturas, pagos, cuentas corrientes con sus movimientos y cierres mensuales.",
                 "Requiere transacciones ACID e integridad referencial: una factura y sus movimientos no pueden quedar "
                 "registrados de forma parcial. El bloqueo de filas impide que dos pagos simultáneos superen el saldo "
                 "de una factura."),
                ("MongoDB", "Documental",
                 "Envíos con sus tramos, eventos logísticos, lecturas de sensores IoT, incidentes, alertas, mensajes, "
                 "grupos de trabajo, reportes y predicciones de riesgo.",
                 "El envío se consulta y modifica como una unidad, y los reportes se resuelven con consultas de "
                 "agregación básicas. Las lecturas IoT se guardan en una colección común indexada por sensor y fecha, "
                 "y por contenedor y fecha."),
                ("Neo4j", "Grafos",
                 "Red de clientes, envíos, tramos, ubicaciones, operadores, vehículos y contenedores.",
                 "Las consultas avanzadas son de relaciones (ruta completa de un envío, clientes que comparten "
                 "operador, envíos activos que pasan por un puerto). En un modelo relacional requerirían múltiples "
                 "JOIN."),
                ("Redis", "Clave-valor",
                 "Sesiones activas, señal de vida y última lectura de cada sensor, posición actual de cada contenedor "
                 "y alertas en tiempo real.",
                 "Ofrece acceso muy rápido, claves con expiración automática y búsqueda por distancia geográfica. La "
                 "expiración resuelve el vencimiento de sesiones y la detección de sensores inactivos sin lógica "
                 "adicional."),
            ])},
        ],
    },
    {
        "titulo": "Ventajas y desventajas de cada motor",
        "bloques": [
            {"parrafo": (
                "Para cada motor se indican sus principales ventajas y desventajas, y cómo cada una influye en qué "
                "información se almacena en él y en cómo se diseña la solución.")},
            {"subtitulo": "PostgreSQL"},
            {"tabla": (COLUMNAS_VENTAJAS, [
                ("Ventaja", "Transacciones ACID que abarcan varias tablas.",
                 "La facturación de un cliente registra la factura, sus ítems y los movimientos de todas las cuentas "
                 "involucradas en una única transacción. Por este motivo el dinero se almacena en PostgreSQL."),
                ("Ventaja", "Restricciones declaradas en la base: claves primarias, claves foráneas, unicidad y "
                 "reglas de validación.",
                 "Las reglas que nunca deben violarse quedan garantizadas por la base: CUIT único, un único titular "
                 "por cuenta corriente, saldo final igual al saldo inicial más débitos menos créditos y un envío "
                 "facturado una sola vez."),
                ("Ventaja", "Bloqueo de filas durante una transacción.",
                 "Se utiliza al reservar contenedores y al registrar un pago, de modo que dos operaciones "
                 "simultáneas no reserven el mismo contenedor ni paguen más que el saldo de una factura."),
                ("Desventaja", "Esquema rígido: modificar la estructura requiere alterar las tablas.",
                 "Solo se almacenan entidades de estructura estable, como los datos maestros y el dinero. El envío, "
                 "que incorpora tramos y datos a medida que avanza, se almacena en MongoDB."),
                ("Desventaja", "Las listas anidadas requieren tablas adicionales y uniones entre tablas.",
                 "Los tramos de un envío y las lecturas de sensores no se modelan en PostgreSQL, porque cada "
                 "consulta obligaría a unir varias tablas."),
                ("Desventaja", "Escala principalmente aumentando la capacidad de un único servidor.",
                 "Es suficiente para el volumen de datos maestros y contables. Los datos de mayor volumen (lecturas "
                 "IoT, eventos y mensajes) se almacenan en MongoDB, que admite distribución horizontal."),
            ])},
            {"subtitulo": "MongoDB"},
            {"tabla": (COLUMNAS_VENTAJAS, [
                ("Ventaja", "Un documento agrupa datos relacionados, incluidos subdocumentos y arreglos.",
                 "El envío se almacena con sus tramos y sus contenedores en un único documento, que se lee y se "
                 "actualiza en una sola operación."),
                ("Ventaja", "Esquema flexible con validación mediante $jsonSchema.",
                 "El envío incorpora campos a medida que avanza (último evento, días de entrega, demora) sin "
                 "modificar una estructura fija, y la validación impide guardar documentos incompletos o con valores "
                 "fuera de rango."),
                ("Ventaja", "Índices compuestos y consultas de agregación.",
                 "Las lecturas IoT se consultan por sensor y fecha, y los reportes (envíos por país, tiempos de "
                 "entrega, costos por medio de transporte) se resuelven agrupando los datos en la base."),
                ("Desventaja", "No ofrece uniones eficientes entre colecciones.",
                 "El envío guarda una copia de los datos del cliente, del operador y del vehículo vigentes al "
                 "crearlo. La copia conserva el valor histórico, pero no se actualiza si el dato cambia en "
                 "PostgreSQL."),
                ("Desventaja", "Las operaciones sobre varios documentos no son atómicas si no se usan transacciones, "
                 "que este trabajo no utiliza.",
                 "Las operaciones que afectan a más de un documento, como registrar un evento y actualizar el estado "
                 "del envío, se diseñan para poder repetirse sin duplicar datos, y el control de integridad corrige "
                 "los contadores que queden desactualizados."),
                ("Desventaja", "No admite claves foráneas.",
                 "Antes de escribir, la aplicación verifica en PostgreSQL que existan el cliente, los contenedores y "
                 "los vehículos referenciados. El control de integridad verifica que todo envío facturado tenga su "
                 "ítem de factura."),
            ])},
            {"subtitulo": "Neo4j"},
            {"tabla": (COLUMNAS_VENTAJAS, [
                ("Ventaja", "Consultas de recorridos de varios saltos expresadas como patrones.",
                 "La ruta completa de un envío, los clientes que comparten operador y el impacto de una ubicación se "
                 "resuelven siguiendo relaciones, sin unir tablas."),
                ("Ventaja", "Escritura idempotente: crear un nodo o relación solo si no existe.",
                 "Proyectar dos veces el mismo envío no duplica nodos ni relaciones, lo que permite reconstruir el "
                 "grafo cuando sea necesario."),
                ("Ventaja", "Restricciones de unicidad por tipo de nodo.",
                 "Cada cliente, envío, tramo, ubicación, operador, vehículo y contenedor existe una sola vez en el "
                 "grafo."),
                ("Desventaja", "No es adecuado para agregaciones masivas ni para datos transaccionales.",
                 "Neo4j no es fuente de verdad: almacena solo una copia de lectura de las relaciones. Los reportes "
                 "y el dinero se resuelven en MongoDB y PostgreSQL."),
                ("Desventaja", "La edición Community no ofrece replicación ni distribución.",
                 "Como el grafo puede reconstruirse completo desde PostgreSQL y MongoDB, una falla de Neo4j no "
                 "provoca pérdida de datos."),
                ("Desventaja", "Es un motor adicional que debe mantenerse sincronizado.",
                 "Cada envío registra si su copia en el grafo está al día. Si Neo4j no responde, la operación "
                 "principal continúa y la opción \"Resincronizar grafo\" completa lo pendiente."),
            ])},
            {"subtitulo": "Redis"},
            {"tabla": (COLUMNAS_VENTAJAS, [
                ("Ventaja", "Acceso en memoria, con tiempos de respuesta muy bajos.",
                 "Se consulta en cada acción del usuario, para validar la sesión, y en cada lectura de sensor, "
                 "operaciones que deben responder de inmediato."),
                ("Ventaja", "Claves con vencimiento automático.",
                 "La sesión vence tras 30 minutos sin uso y la señal de vida de un sensor tras 15 minutos, sin "
                 "procesos de limpieza. La ausencia de la clave indica que el sensor dejó de reportar."),
                ("Ventaja", "Estructuras específicas para búsqueda geográfica y publicación de mensajes.",
                 "La posición actual de los contenedores permite buscar los que se encuentran dentro de un radio, y "
                 "las alertas se publican en tiempo real para el monitor de alertas."),
                ("Desventaja", "Los datos residen en memoria; con escritura a disco cada segundo, una falla puede "
                 "perder hasta el último segundo de datos.",
                 "Solo se almacenan datos que pueden reconstruirse: el historial de sesiones se guarda en PostgreSQL "
                 "y las lecturas, en MongoDB."),
                ("Desventaja", "Solo permite acceder por clave, sin consultas por contenido.",
                 "Las claves se diseñan según la forma de acceso (por ejemplo, la sesión por su identificador y la "
                 "última lectura por sensor), y un conjunto por usuario permite listar sus sesiones."),
                ("Desventaja", "La capacidad está limitada por la memoria disponible.",
                 "Se guarda solo el estado actual (última lectura y posición actual), no el historial, que crece sin "
                 "límite y se almacena en MongoDB."),
            ])},
        ],
    },
    {
        "titulo": "Modelado de las estructuras de datos",
        "bloques": [
            {"parrafo": (
                "Se describe la estructura de los datos en cada motor, tal como la crean los scripts de creación de "
                "bases de datos.")},
            {"subtitulo": "PostgreSQL: tablas"},
            {"parrafo": (
                "Notación: PK es la clave primaria, FK una clave foránea hacia la tabla indicada y «único» una "
                "restricción de unicidad. Los identificadores se generan automáticamente. Clientes y empresas se dan "
                "de baja de forma lógica (estado BAJA), porque otros motores los referencian.")},
            {"tabla": ([("Tabla", 3.6), ("Columnas", 6.0), ("Claves y restricciones", 6.4)], [
                ("rol", "id, descripcion, nivel_permisos",
                 "PK id. Descripción única. Nivel entre 1 y 5. Datos fijos: ADMIN (5), OPERADOR (3), CLIENTE (1)."),
                ("cliente", "id, razon_social, cuit, email, telefono, direccion, pais, estado",
                 "PK id. CUIT único con formato NN-NNNNNNNN-N. País de 2 letras. Estado ACTIVO, INACTIVO o BAJA."),
                ("empresa", "id, tipo, razon_social, cuit, pais, estado",
                 "PK id. Tipo OPERADOR o PROVEEDOR. CUIT único. Estado ACTIVO, INACTIVO o BAJA."),
                ("usuario", "id, cliente_id, nombre, apellido, email, password_hash, estado, fecha_registro",
                 "PK id. FK cliente_id → cliente (vacío en usuarios internos). Email único. Contraseña encriptada "
                 "con bcrypt. Estado ACTIVO, BLOQUEADO o BAJA."),
                ("usuario_rol", "usuario_id, rol_id",
                 "PK (usuario_id, rol_id). FK usuario_id → usuario. FK rol_id → rol."),
                ("sesion", "id, usuario_id, fecha_inicio, fecha_fin, estado",
                 "PK id (UUID). FK usuario_id → usuario. Estado ACTIVA, CERRADA o EXPIRADA. La fecha de fin es "
                 "posterior al inicio y solo está vacía si la sesión está activa."),
                ("contenedor", "id, codigo_internacional, tipo, capacidad_m3, temp_min, temp_max, estado",
                 "PK id. Código ISO 6346 único (4 letras y 7 dígitos). Capacidad mayor a cero. Temperatura mínima "
                 "menor que la máxima. Estado DISPONIBLE, EN_USO, MANTENIMIENTO o BAJA."),
                ("sensor", "id, tipo, fabricante, fecha_instalacion, estado, contenedor_id",
                 "PK id. FK contenedor_id → contenedor (vacío si no está asociado). Estado ACTIVO, INACTIVO, FALLA o "
                 "BAJA."),
                ("vehiculo", "id, tipo, identificacion, empresa_id, estado",
                 "PK id. Identificación única. FK empresa_id → empresa. Tipo CAMION, TREN, BUQUE o AVION."),
                ("cuenta_corriente", "id, cliente_id, empresa_id, saldo, fecha_actualizacion",
                 "PK id. FK cliente_id → cliente y FK empresa_id → empresa, ambas únicas. Exactamente uno de los dos "
                 "titulares."),
                ("factura", "id, cliente_id, periodo, fecha_emision, importe_total, estado",
                 "PK id. FK cliente_id → cliente. Período AAAA-MM. Importe mayor a cero. Estado EMITIDA, "
                 "PAGADA_PARCIAL, PAGADA o ANULADA."),
                ("factura_item", "id, factura_id, envio_id, importe",
                 "PK id. FK factura_id → factura. envio_id único: un envío se factura una sola vez. Referencia al "
                 "envío almacenado en MongoDB."),
                ("pago", "id, factura_id, fecha, monto, medio_pago",
                 "PK id. FK factura_id → factura. Monto mayor a cero. Medio TRANSFERENCIA, TARJETA, CHEQUE o "
                 "EFECTIVO."),
                ("movimiento_cc", "id, cuenta_id, fecha, tipo, importe, factura_id, pago_id, envio_id, descripcion",
                 "PK id. FK cuenta_id → cuenta_corriente, FK factura_id → factura y FK pago_id → pago. Tipo DEBE o "
                 "HABER. Un solo movimiento por cuenta y envío."),
                ("cierre_cc", "cuenta_id, periodo, saldo_inicial, total_debe, total_haber, saldo_final",
                 "PK (cuenta_id, periodo). FK cuenta_id → cuenta_corriente. Saldo final igual al saldo inicial más "
                 "el total del debe menos el total del haber."),
            ])},
            {"parrafo": "Relaciones entre las tablas:"},
            {"tabla": ([("Relación", 6.0), ("Cardinalidad y significado", 10.0)], [
                ("cliente – usuario", "1 a N. Un cliente tiene varios usuarios; los usuarios internos no tienen cliente."),
                ("usuario – rol", "N a M, mediante la tabla usuario_rol."),
                ("usuario – sesion", "1 a N. Historial de sesiones de cada usuario."),
                ("cliente o empresa – cuenta_corriente", "1 a 1. Cada cliente y cada empresa tiene una cuenta."),
                ("empresa – vehiculo", "1 a N. Un operador logístico tiene varios vehículos."),
                ("contenedor – sensor", "1 a N. Un contenedor tiene varios sensores instalados."),
                ("cliente – factura", "1 a N. Una factura por cliente y período facturado."),
                ("factura – factura_item", "1 a N. Cada ítem corresponde a un envío almacenado en MongoDB."),
                ("factura – pago", "1 a N. Una factura puede cancelarse con varios pagos."),
                ("cuenta_corriente – movimiento_cc", "1 a N. Débitos y créditos de la cuenta."),
                ("cuenta_corriente – cierre_cc", "1 a N. Un cierre por cuenta y período."),
            ])},
            {"subtitulo": "MongoDB: colecciones"},
            {"parrafo": (
                "Notación: {…} indica un subdocumento y […] un arreglo. Todas las colecciones validan su estructura "
                "con $jsonSchema. Los identificadores son enteros secuenciales, salvo en eventos, lecturas y "
                "mensajes, que usan el identificador automático de MongoDB.")},
            {"tabla": ([("Colección", 2.8), ("Estructura del documento", 8.4), ("Índices", 4.8)], [
                ("envios",
                 "_id · cliente {id, razon_social, pais} · fecha_creacion · origen y destino {codigo, ciudad, pais} · "
                 "estado · prioridad · peso_kg · volumen_m3 · contenedores [{id, codigo}] · tramos [{id, orden, "
                 "medio, origen, destino, operador {id, razon_social}, vehiculo {id, identificacion}, fecha_salida, "
                 "fecha_llegada_estimada, costo}] · fecha_entrega_estimada · fecha_entrega_real · "
                 "cantidad_incidentes · ultimo_evento {tipo, fecha_hora, ubicacion} · facturado · factura_id · "
                 "grafo_sincronizado · al entregarse: dias_entrega, demorado, mes_entrega",
                 "Cliente y fecha de creación. Estado y entrega estimada. País de destino. Contenedor y estado. "
                 "Pendientes de facturar (parcial). Pendientes de sincronizar con el grafo."),
                ("lecturas",
                 "sensor_id · contenedor_id · fecha_hora · temperatura · humedad · vibracion · lat · lon · bateria "
                 "(las medidas son opcionales, con rangos validados)",
                 "Sensor y fecha. Contenedor y fecha."),
                ("eventos",
                 "envio_id · contenedor_ids [ ] · fecha_hora · tipo · ubicacion · descripcion",
                 "Único por envío, fecha y tipo. Contenedor y fecha."),
                ("incidentes",
                 "_id · envio_id · tramo_id · ruta (origen-destino del envío) · tipo · fecha · severidad · estado · "
                 "descripcion · fecha_cierre",
                 "Estado y fecha. Envío y estado."),
                ("alertas",
                 "_id · sensor_id · contenedor_id · envio_id · evento {origen, fecha_hora} · tipo · fecha · estado · "
                 "valor · umbral · fecha_cierre",
                 "Único por sensor y tipo mientras la alerta está abierta (parcial). Contenedor y estado."),
                ("mensajes",
                 "conversacion_id · tipo · remitente_id · destinatario {tipo, id} · participantes [ ] (solo en "
                 "privados) · fecha_hora · contenido",
                 "Conversación y fecha. Participante y fecha."),
                ("grupos", "_id · nombre · publico · integrantes [{usuario_id}] (al menos dos)",
                 "Integrante."),
                ("reportes",
                 "_id · usuario_id · tipo · parametros {desde, hasta, cliente_id} · formato · fecha_generacion · "
                 "estado · resultado [ ]",
                 "Sin índices adicionales."),
                ("predicciones",
                 "_id · envio_id · dia · probabilidad_demora · riesgo_climatico · riesgo_operativo · fecha_calculo · "
                 "factores { }",
                 "Único por envío y día."),
                ("contadores", "_id (nombre de la colección) · valor (último identificador asignado)",
                 "Sin índices adicionales."),
            ])},
            {"parrafo": "Criterio para embeber o referenciar los datos:"},
            {"tabla": ([("Dato", 4.4), ("Decisión", 4.2), ("Motivo", 7.4)], [
                ("Tramos del envío", "Embebidos en el envío.",
                 "Son pocos por envío y siempre se consultan junto con él."),
                ("Cliente, operador y vehículo", "Copia parcial dentro del envío.",
                 "Conserva los datos vigentes al momento del envío y evita consultar PostgreSQL al mostrarlo."),
                ("Contenedores del envío", "Identificador y código dentro del envío.",
                 "Permite buscar mediante un índice los envíos de un contenedor."),
                ("Eventos, incidentes y lecturas", "Colecciones separadas que referencian al envío.",
                 "Crecen sin límite y tienen un ciclo de vida propio."),
            ])},
            {"parrafo": "Ejemplo de documento de la colección envios (envío entregado con demora):"},
            {"codigo": EJEMPLO_ENVIO},
            {"subtitulo": "Neo4j: nodos y relaciones"},
            {"parrafo": (
                "El grafo es una copia de lectura que se genera a partir de PostgreSQL y MongoDB. Cada tipo de nodo "
                "tiene una restricción de unicidad sobre su clave.")},
            {"tabla": ([("Nodo", 3.0), ("Propiedades", 9.0), ("Clave única", 4.0)], [
                ("Cliente", "id, razon_social, pais", "id"),
                ("Envio", "id, estado, prioridad, fecha_creacion, origen, destino", "id"),
                ("Tramo", "id, orden, medio, fecha_salida, fecha_llegada_estimada", "id"),
                ("Ubicacion", "codigo, ciudad, pais", "codigo"),
                ("Operador", "id, razon_social", "id"),
                ("Vehiculo", "id, identificacion", "id"),
                ("Contenedor", "id, codigo", "id"),
            ])},
            {"parrafo": "Relaciones entre los nodos:"},
            {"tabla": ([("Relación", 3.6), ("Origen → destino", 5.0), ("Significado", 7.4)], [
                ("SOLICITO", "Cliente → Envio", "El cliente solicitó el envío."),
                ("INCLUYE", "Envio → Tramo", "El envío se compone del tramo."),
                ("DESDE", "Tramo → Ubicacion", "Ubicación de salida del tramo."),
                ("HASTA", "Tramo → Ubicacion", "Ubicación de llegada del tramo."),
                ("OPERADO_POR", "Tramo → Operador", "Empresa que realiza el tramo."),
                ("EN_VEHICULO", "Tramo → Vehiculo", "Vehículo que realiza el tramo."),
                ("TRANSPORTA", "Envio → Contenedor", "Contenedor que lleva el envío."),
            ])},
            {"subtitulo": "Redis: claves"},
            {"tabla": ([("Clave", 4.2), ("Tipo", 2.3), ("Contenido", 6.2), ("Vencimiento", 3.3)], [
                ("sesion:{id}", "HASH", "Usuario, nombre, nivel de permisos, roles y cliente de la sesión.",
                 "30 minutos; se renueva con cada acción."),
                ("usuario:{id}:sesiones", "SET", "Identificadores de las sesiones abiertas del usuario.",
                 "Sin vencimiento."),
                ("sensor:{id}:hb", "STRING", "Momento de la última transmisión del sensor.", "15 minutos."),
                ("sensor:{id}:ultima", "HASH", "Fecha y medidas de la lectura más reciente del sensor.",
                 "Sin vencimiento."),
                ("contenedores:geo", "GEO", "Posición actual (longitud y latitud) de cada contenedor.",
                 "Sin vencimiento."),
                ("alertas", "Canal PUB/SUB", "Alertas generadas, publicadas en el momento en que ocurren.",
                 "No se almacena."),
            ])},
        ],
    },
    {
        "titulo": "Librerías de Python",
        "bloques": [
            {"tabla": ([("Librería", 5.0), ("Uso", 11.0)], [
                ("psycopg", "Conexión con PostgreSQL."),
                ("pymongo", "Conexión con MongoDB."),
                ("neo4j", "Conexión con Neo4j."),
                ("redis", "Conexión con Redis."),
                ("bcrypt", "Almacenamiento encriptado de contraseñas, requerido por el enunciado."),
                ("python-dotenv", "Lectura de la configuración y las credenciales desde un archivo separado del código."),
                ("logging (librería estándar)", "Registro de logs, requerido por el enunciado."),
                ("json y csv (librería estándar)", "Exportación de los reportes generados a archivos en formato JSON o CSV."),
                ("argparse (librería estándar)",
                 "Lectura de los parámetros del simulador de sensores IoT, que genera lecturas periódicas."),
                ("getpass (librería estándar)", "Ingreso de la contraseña en la consola sin mostrarla en pantalla."),
                ("pytest", "Casos de prueba, requeridos por el enunciado."),
            ])},
        ],
    },
    {
        "titulo": "Arquitectura y calidad",
        "bloques": [
            {"tabla": ([("Decisión", 5.0), ("Justificación", 11.0)], [
                ("Separación en capas: interfaz, servicios, repositorios y bases de datos",
                 "Requerido por el enunciado. Un cambio en una base de datos solo afecta a su repositorio."),
                ("Reglas de negocio en un módulo independiente",
                 "Las reglas (importe facturado, detección de anomalías, predicción de demoras) no dependen de ninguna "
                 "base de datos, por lo que se prueban sin levantar los motores."),
                ("Un repositorio por base de datos", "Aísla cada motor y facilita explicar la función de cada uno."),
                ("Armado de componentes en un único módulo",
                 "Las conexiones, los repositorios y los servicios se crean en un solo lugar, lo que deja visible qué "
                 "componente utiliza cada base."),
                ("Errores propios del negocio",
                 "Control de errores: el usuario recibe mensajes claros y el detalle técnico queda registrado en el log."),
                ("Menú y datos filtrados por rol",
                 "Cada usuario ve solo las opciones de su rol, y un usuario de un cliente accede únicamente a sus "
                 "envíos, su cuenta corriente y sus reportes."),
                ("Neo4j como copia de lectura con opción de resincronización",
                 "El grafo se alimenta de PostgreSQL y MongoDB; ante una falla puede reconstruirse sin pérdida de datos."),
                ("Operaciones repetibles sin duplicar datos",
                 "Los índices únicos impiden que un reintento duplique eventos, alertas, ítems de factura o "
                 "predicciones, por lo que una operación interrumpida puede volver a ejecutarse."),
                ("Bloqueo de filas en reservas y pagos",
                 "Evita que dos operaciones simultáneas reserven el mismo contenedor o paguen más que el saldo de una "
                 "factura."),
                ("Datos de prueba cargados a través de la aplicación",
                 "Garantiza la coherencia de los datos entre las cuatro bases."),
                ("Controles de integridad entre bases",
                 "Requerido por el enunciado. Verifica, por ejemplo, que todo envío facturado tenga su ítem de factura "
                 "y que la cantidad de incidentes registrada en cada envío coincida con los incidentes existentes."),
            ])},
        ],
    },
]


def _elemento(nombre: str, **atributos) -> OxmlElement:
    elemento = OxmlElement(nombre)
    for clave, valor in atributos.items():
        elemento.set(qn(f"w:{clave}"), str(valor))
    return elemento


def _dxa(centimetros: float) -> int:
    return round(centimetros * 567)


def configurar_pagina(documento: Document) -> None:
    seccion = documento.sections[0]
    seccion.page_width, seccion.page_height = Cm(21), Cm(29.7)
    for margen in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(seccion, margen, Cm(2.5))


def _estilo_titulo(estilo, tamanio: int, color: RGBColor, antes: int, despues: int) -> None:
    fuentes = estilo.element.get_or_add_rPr().get_or_add_rFonts()
    for atributo in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        fuentes.attrib.pop(qn(f"w:{atributo}"), None)
    estilo.font.name = FUENTE
    estilo.font.size = Pt(tamanio)
    estilo.font.bold = True
    estilo.font.italic = False
    estilo.font.color.rgb = color
    fuentes.set(qn("w:eastAsia"), FUENTE)
    estilo.paragraph_format.space_before = Pt(antes)
    estilo.paragraph_format.space_after = Pt(despues)
    estilo.paragraph_format.keep_with_next = True


def configurar_estilos(documento: Document) -> None:
    normal = documento.styles["Normal"]
    normal.font.name = FUENTE
    normal.font.size = Pt(11)
    normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FUENTE)
    normal.paragraph_format.space_after = Pt(6)
    _estilo_titulo(documento.styles["Heading 1"], 14, AZUL_TITULOS, 18, 8)
    _estilo_titulo(documento.styles["Heading 2"], 12, AZUL_SUBTITULOS, 12, 6)


def _texto_gris(parrafo, texto: str) -> None:
    corrida = parrafo.add_run(texto)
    corrida.font.color.rgb = GRIS
    corrida.font.size = Pt(9)


def agregar_pie_de_pagina(documento: Document) -> None:
    parrafo = documento.sections[0].footer.paragraphs[0]
    parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _texto_gris(parrafo, "Página ")
    corrida = parrafo.add_run()
    corrida.font.color.rgb = GRIS
    corrida.font.size = Pt(9)
    corrida._r.append(_elemento("w:fldChar", fldCharType="begin"))
    instruccion = _elemento("w:instrText")
    instruccion.set(qn("xml:space"), "preserve")
    instruccion.text = " PAGE "
    corrida._r.append(instruccion)
    corrida._r.append(_elemento("w:fldChar", fldCharType="separate"))
    corrida._r.append(_elemento("w:t"))
    corrida._r[-1].text = "1"
    corrida._r.append(_elemento("w:fldChar", fldCharType="end"))


def agregar_portada(documento: Document) -> None:
    titulo = documento.add_paragraph()
    corrida = titulo.add_run(PORTADA["titulo"])
    corrida.bold = True
    corrida.font.size = Pt(18)
    corrida.font.color.rgb = AZUL_TITULOS
    titulo.paragraph_format.space_after = Pt(4)

    subtitulo = documento.add_paragraph()
    corrida = subtitulo.add_run(PORTADA["subtitulo"])
    corrida.font.size = Pt(13)
    corrida.font.color.rgb = GRIS
    subtitulo.paragraph_format.space_after = Pt(14)
    bordes = _elemento("w:pBdr")
    bordes.append(_elemento("w:bottom", val="single", sz=12, space=6, color=COLOR_SEPARADOR))
    subtitulo._p.get_or_add_pPr().insert_element_before(bordes, "w:shd", "w:tabs", "w:spacing", "w:ind", "w:jc",
                                                        "w:rPr")

    for etiqueta, valor in PORTADA["datos"]:
        parrafo = documento.add_paragraph()
        parrafo.paragraph_format.space_after = Pt(2)
        parrafo.add_run(f"{etiqueta}: ").bold = True
        parrafo.add_run(valor)


def _configurar_tabla(tabla, anchos_cm: list[float], fondo: str | None = None) -> None:
    propiedades = tabla._tbl.tblPr
    conservados = {hijo.tag: hijo for hijo in propiedades if hijo.tag in (qn("w:tblStyle"), qn("w:jc"), qn("w:tblLook"))}
    for hijo in list(propiedades):
        propiedades.remove(hijo)
    bordes = _elemento("w:tblBorders")
    for lado in ("top", "left", "bottom", "right", "insideH", "insideV"):
        bordes.append(_elemento(f"w:{lado}", val="single", sz=4, space=0, color=COLOR_BORDE_TABLA))
    margenes = _elemento("w:tblCellMar")
    for lado, valor in (("top", 60), ("left", 100), ("bottom", 60), ("right", 100)):
        margenes.append(_elemento(f"w:{lado}", w=valor, type="dxa"))
    sombreado = _elemento("w:shd", val="clear", color="auto", fill=fondo) if fondo else None
    for hijo in (conservados.get(qn("w:tblStyle")), _elemento("w:tblW", w=_dxa(sum(anchos_cm)), type="dxa"),
                 conservados.get(qn("w:jc")), bordes, sombreado, _elemento("w:tblLayout", type="fixed"), margenes,
                 conservados.get(qn("w:tblLook"))):
        if hijo is not None:
            propiedades.append(hijo)
    grilla = tabla._tbl.tblGrid
    for columna, ancho in zip(grilla.findall(qn("w:gridCol")), anchos_cm):
        columna.set(qn("w:w"), str(_dxa(ancho)))


def _configurar_fila(fila, es_encabezado: bool) -> None:
    propiedades = fila._tr.get_or_add_trPr()
    propiedades.append(_elemento("w:cantSplit"))
    if es_encabezado:
        propiedades.append(_elemento("w:tblHeader"))


def _escribir_celda(celda, texto: str, ancho_cm: float, es_encabezado: bool, resaltar: bool) -> None:
    celda.width = Cm(ancho_cm)
    parrafo = celda.paragraphs[0]
    parrafo.paragraph_format.space_after = Pt(0)
    parrafo.paragraph_format.keep_with_next = es_encabezado
    corrida = parrafo.add_run(texto)
    corrida.font.size = Pt(10)
    corrida.bold = es_encabezado or resaltar
    if es_encabezado:
        celda._tc.get_or_add_tcPr().append(_elemento("w:shd", val="clear", color="auto", fill=FONDO_ENCABEZADO))


def agregar_tabla(documento: Document, columnas: list[tuple[str, float]], filas: list[tuple[str, ...]]) -> None:
    anchos = [ancho for _, ancho in columnas]
    tabla = documento.add_table(rows=1 + len(filas), cols=len(columnas))
    tabla.alignment = WD_TABLE_ALIGNMENT.CENTER
    tabla.autofit = False
    _configurar_tabla(tabla, anchos)
    contenido = [tuple(nombre for nombre, _ in columnas), *filas]
    for indice, (fila, valores) in enumerate(zip(tabla.rows, contenido)):
        _configurar_fila(fila, es_encabezado=indice == 0)
        for columna, (celda, texto, ancho) in enumerate(zip(fila.cells, valores, anchos)):
            _escribir_celda(celda, texto, ancho, es_encabezado=indice == 0, resaltar=indice > 0 and columna == 0)
    documento.add_paragraph().paragraph_format.space_after = Pt(0)


def agregar_codigo(documento: Document, texto: str) -> None:
    tabla = documento.add_table(rows=1, cols=1)
    tabla.alignment = WD_TABLE_ALIGNMENT.CENTER
    tabla.autofit = False
    _configurar_tabla(tabla, [ANCHO_UTIL_CM], fondo=FONDO_CODIGO)
    _configurar_fila(tabla.rows[0], es_encabezado=False)
    celda = tabla.rows[0].cells[0]
    celda.width = Cm(ANCHO_UTIL_CM)
    celda._tc.get_or_add_tcPr().append(_elemento("w:shd", val="clear", color="auto", fill=FONDO_CODIGO))
    parrafo = celda.paragraphs[0]
    parrafo.paragraph_format.space_after = Pt(0)
    for numero, linea in enumerate(texto.splitlines()):
        corrida = parrafo.add_run(linea)
        corrida.font.name = FUENTE_CODIGO
        corrida._r.get_or_add_rPr().get_or_add_rFonts().set(qn("w:hAnsi"), FUENTE_CODIGO)
        corrida.font.size = Pt(8)
        if numero < len(texto.splitlines()) - 1:
            corrida.add_break()
    documento.add_paragraph().paragraph_format.space_after = Pt(0)


def agregar_seccion(documento: Document, seccion: dict) -> None:
    documento.add_heading(seccion["titulo"], level=1)
    for bloque in seccion["bloques"]:
        if "subtitulo" in bloque:
            documento.add_heading(bloque["subtitulo"], level=2)
        elif "parrafo" in bloque:
            parrafo = documento.add_paragraph(bloque["parrafo"])
            parrafo.paragraph_format.keep_with_next = True
        elif "tabla" in bloque:
            agregar_tabla(documento, *bloque["tabla"])
        elif "codigo" in bloque:
            agregar_codigo(documento, bloque["codigo"])


def validar_anchos() -> None:
    for seccion in SECCIONES:
        for bloque in seccion["bloques"]:
            if "tabla" in bloque:
                total = sum(ancho for _, ancho in bloque["tabla"][0])
                assert abs(total - ANCHO_UTIL_CM) < 0.01, f"{seccion['titulo']}: {total} cm"


def configurar_propiedades(documento: Document) -> None:
    propiedades = documento.core_properties
    propiedades.title = f"{PORTADA['titulo']} - {PORTADA['subtitulo']}"
    propiedades.author = propiedades.last_modified_by = dict(PORTADA["datos"])["Integrantes"]
    propiedades.comments = ""


def generar() -> Path:
    validar_anchos()
    documento = Document()
    configurar_propiedades(documento)
    configurar_pagina(documento)
    configurar_estilos(documento)
    agregar_pie_de_pagina(documento)
    agregar_portada(documento)
    for seccion in SECCIONES:
        agregar_seccion(documento, seccion)
    documento.save(SALIDA)
    return SALIDA


if __name__ == "__main__":
    try:
        print(f"Documento generado: {generar()}")
    except PermissionError:
        raise SystemExit(f"No se pudo escribir {SALIDA.name}: cerralo en Word y volvé a ejecutar el script.")
