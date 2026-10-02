import logging

from neo4j.exceptions import DriverError, Neo4jError

from app.repositorios.documental import RepositorioDocumental
from app.repositorios.grafo import RepositorioGrafo
from app.repositorios.relacional import RepositorioRelacional
from app.servicios.auth import NIVEL_ADMIN, SesionActiva, requerir_nivel

log = logging.getLogger(__name__)


class ServicioSincronizacion:
    def __init__(self, relacional: RepositorioRelacional, documental: RepositorioDocumental,
                 grafo: RepositorioGrafo):
        self._rel = relacional
        self._doc = documental
        self._grafo = grafo

    def proyectar_envio(self, envio_id: int) -> bool:
        try:
            self._grafo.proyectar_envio(self._doc.obtener_envio(envio_id))
        except (Neo4jError, DriverError) as error:
            log.warning("Neo4j no disponible (%s): el envío %s queda pendiente de sincronizar",
                        type(error).__name__, envio_id)
            return False
        self._doc.marcar_sincronizado(envio_id)
        return True

    def proyectar_cliente(self, cliente_id: int) -> bool:
        try:
            self._grafo.proyectar_cliente(self._rel.obtener_cliente(cliente_id))
        except (Neo4jError, DriverError) as error:
            log.warning("Neo4j no disponible (%s): el cliente %s se proyectará al resincronizar",
                        type(error).__name__, cliente_id)
            return False
        return True

    def resincronizar_grafo(self, sesion: SesionActiva, completo: bool = False) -> dict:
        requerir_nivel(sesion, NIVEL_ADMIN)
        if completo:
            self._grafo.borrar_todo()
        envios = self._doc.todos_los_envios() if completo else self._doc.envios_no_sincronizados()
        clientes = self._rel.listar_clientes()
        for cliente in clientes:
            self._grafo.proyectar_cliente(cliente)
        for envio in envios:
            self._grafo.proyectar_envio(envio)
            self._doc.marcar_sincronizado(envio["_id"])
        log.info("Resincronización del grafo (%s): %s clientes, %s envíos",
                 "completa" if completo else "pendientes", len(clientes), len(envios))
        return {"modo": "completa" if completo else "pendientes", "clientes": len(clientes), "envios": len(envios)}
