// Proyeccion de grafos: solo restricciones de unicidad. Los nodos y relaciones se crean con MERGE
// desde la aplicacion. Idempotente.

CREATE CONSTRAINT cliente_id IF NOT EXISTS FOR (n:Cliente) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT envio_id IF NOT EXISTS FOR (n:Envio) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT tramo_id IF NOT EXISTS FOR (n:Tramo) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT ubicacion_codigo IF NOT EXISTS FOR (n:Ubicacion) REQUIRE n.codigo IS UNIQUE;
CREATE CONSTRAINT operador_id IF NOT EXISTS FOR (n:Operador) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT vehiculo_id IF NOT EXISTS FOR (n:Vehiculo) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT contenedor_id IF NOT EXISTS FOR (n:Contenedor) REQUIRE n.id IS UNIQUE;
