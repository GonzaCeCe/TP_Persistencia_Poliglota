from neo4j import ManagedTransaction
from neo4j.exceptions import ConstraintError

from app.dominio.reglas import ESTADOS_CERRADOS
from app.infra.conexiones import Conexiones
from app.infra.errores import IntegridadError

PROYECTAR_CLIENTE = """
MERGE (c:Cliente {id: $id})
SET c.razon_social = $razon_social, c.pais = $pais
"""

PROYECTAR_ENVIO = """
MERGE (c:Cliente {id: $cliente.id})
  ON CREATE SET c.razon_social = $cliente.razon_social, c.pais = $cliente.pais
MERGE (e:Envio {id: $id})
SET e.estado = $estado, e.prioridad = $prioridad, e.fecha_creacion = $fecha_creacion,
    e.origen = $origen, e.destino = $destino
MERGE (c)-[:SOLICITO]->(e)
WITH e
UNWIND $contenedores AS contenedor
MERGE (k:Contenedor {id: contenedor.id})
SET k.codigo = contenedor.codigo
MERGE (e)-[:TRANSPORTA]->(k)
"""

PROYECTAR_TRAMO = """
MATCH (e:Envio {id: $envio_id})
MERGE (t:Tramo {id: $tramo.id})
SET t.orden = $tramo.orden, t.medio = $tramo.medio,
    t.fecha_salida = $tramo.fecha_salida, t.fecha_llegada_estimada = $tramo.fecha_llegada_estimada
MERGE (e)-[:INCLUYE]->(t)
MERGE (o:Ubicacion {codigo: $tramo.origen.codigo})
SET o.ciudad = $tramo.origen.ciudad, o.pais = $tramo.origen.pais
MERGE (d:Ubicacion {codigo: $tramo.destino.codigo})
SET d.ciudad = $tramo.destino.ciudad, d.pais = $tramo.destino.pais
MERGE (t)-[:DESDE]->(o)
MERGE (t)-[:HASTA]->(d)
MERGE (op:Operador {id: $tramo.operador.id})
SET op.razon_social = $tramo.operador.razon_social
MERGE (t)-[:OPERADO_POR]->(op)
MERGE (v:Vehiculo {id: $tramo.vehiculo.id})
SET v.identificacion = $tramo.vehiculo.identificacion
MERGE (t)-[:EN_VEHICULO]->(v)
"""

RUTA_COMPLETA = """
MATCH (e:Envio {id: $envio_id})-[:INCLUYE]->(t:Tramo),
      (t)-[:DESDE]->(o:Ubicacion), (t)-[:HASTA]->(d:Ubicacion),
      (t)-[:OPERADO_POR]->(op:Operador), (t)-[:EN_VEHICULO]->(v:Vehiculo)
RETURN t.orden AS orden, t.medio AS medio, o.codigo AS desde, o.ciudad AS ciudad_desde,
       d.codigo AS hasta, d.ciudad AS ciudad_hasta, op.razon_social AS operador,
       v.identificacion AS vehiculo, t.fecha_salida AS salida, t.fecha_llegada_estimada AS llegada_estimada
ORDER BY orden
"""

RED_CLIENTES_OPERADORES = """
MATCH (c:Cliente)-[:SOLICITO]->(e:Envio)-[:INCLUYE]->(:Tramo)-[:OPERADO_POR]->(op:Operador)
WHERE $cliente_id IS NULL OR c.id = $cliente_id
RETURN c.id AS cliente_id, c.razon_social AS cliente, op.id AS operador_id, op.razon_social AS operador,
       collect(DISTINCT e.id) AS envios
ORDER BY cliente_id, operador_id
"""

CLIENTES_QUE_COMPARTEN_OPERADOR = """
MATCH (c1:Cliente)-[:SOLICITO]->(:Envio)-[:INCLUYE]->(:Tramo)-[:OPERADO_POR]->(op:Operador)
      <-[:OPERADO_POR]-(:Tramo)<-[:INCLUYE]-(:Envio)<-[:SOLICITO]-(c2:Cliente)
WHERE c1.id < c2.id AND ($cliente_id IS NULL OR $cliente_id IN [c1.id, c2.id])
RETURN c1.razon_social AS cliente_a, c2.razon_social AS cliente_b,
       collect(DISTINCT op.razon_social) AS operadores_compartidos
ORDER BY cliente_a, cliente_b
"""

IMPACTO_DE_UBICACION = """
MATCH (u:Ubicacion {codigo: $codigo})<-[:DESDE|HASTA]-(:Tramo)<-[:INCLUYE]-(e:Envio)<-[:SOLICITO]-(c:Cliente)
WHERE NOT e.estado IN $estados_cerrados
RETURN c.id AS cliente_id, c.razon_social AS cliente, collect(DISTINCT e.id) AS envios_activos
ORDER BY cliente_id
"""


class RepositorioGrafo:
    def __init__(self, conexiones: Conexiones):
        self._conexiones = conexiones

    def _escribir(self, funcion, *argumentos) -> None:
        try:
            with self._conexiones.neo4j().session() as sesion:
                sesion.execute_write(funcion, *argumentos)
        except ConstraintError as error:
            raise IntegridadError(f"Restricción del grafo violada: {error.message}") from error

    def _leer(self, consulta: str, **parametros) -> list[dict]:
        with self._conexiones.neo4j().session() as sesion:
            return sesion.execute_read(lambda tx: [registro.data() for registro in tx.run(consulta, **parametros)])

    def proyectar_cliente(self, cliente: dict) -> None:
        self._escribir(lambda tx: tx.run(PROYECTAR_CLIENTE, id=cliente["id"],
                                         razon_social=cliente["razon_social"], pais=cliente["pais"]).consume())

    def proyectar_envio(self, envio: dict) -> None:
        self._escribir(_proyectar_envio, envio)

    def borrar_todo(self) -> None:
        self._escribir(lambda tx: tx.run("MATCH (n) DETACH DELETE n").consume())

    def ruta_completa(self, envio_id: int) -> list[dict]:
        return self._leer(RUTA_COMPLETA, envio_id=envio_id)

    def red_clientes_operadores(self, cliente_id: int | None = None) -> list[dict]:
        return self._leer(RED_CLIENTES_OPERADORES, cliente_id=cliente_id)

    def clientes_que_comparten_operador(self, cliente_id: int | None = None) -> list[dict]:
        return self._leer(CLIENTES_QUE_COMPARTEN_OPERADOR, cliente_id=cliente_id)

    def impacto_de_ubicacion(self, codigo: str) -> list[dict]:
        return self._leer(IMPACTO_DE_UBICACION, codigo=codigo, estados_cerrados=sorted(ESTADOS_CERRADOS))


def _proyectar_envio(tx: ManagedTransaction, envio: dict) -> None:
    tx.run(PROYECTAR_ENVIO, id=envio["_id"], cliente=envio["cliente"], estado=envio["estado"],
           prioridad=envio["prioridad"], fecha_creacion=envio["fecha_creacion"],
           origen=envio["origen"]["codigo"], destino=envio["destino"]["codigo"],
           contenedores=envio["contenedores"]).consume()
    for tramo in envio["tramos"]:
        tx.run(PROYECTAR_TRAMO, envio_id=envio["_id"], tramo=tramo).consume()
