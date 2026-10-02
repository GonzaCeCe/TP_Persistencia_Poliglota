from dataclasses import dataclass

from app.config import Config, cargar_config
from app.infra.conexiones import Conexiones
from app.infra.logs import configurar_logs
from app.repositorios.clave_valor import RepositorioClaveValor
from app.repositorios.documental import RepositorioDocumental
from app.repositorios.grafo import RepositorioGrafo
from app.repositorios.relacional import RepositorioRelacional
from app.servicios.auth import ServicioAuth
from app.servicios.comercial import ServicioComercial
from app.servicios.mensajeria import ServicioMensajeria
from app.servicios.monitoreo import ServicioMonitoreo
from app.servicios.operativa import ServicioOperativa
from app.servicios.prediccion import ClimaSinFuenteDeDatos, ServicioPrediccion
from app.servicios.reportes import ServicioReportes
from app.servicios.sincronizacion import ServicioSincronizacion
from app.servicios.trazabilidad import ServicioTrazabilidad


@dataclass(frozen=True)
class Aplicacion:
    config: Config
    conexiones: Conexiones
    auth: ServicioAuth
    operativa: ServicioOperativa
    monitoreo: ServicioMonitoreo
    trazabilidad: ServicioTrazabilidad
    mensajeria: ServicioMensajeria
    comercial: ServicioComercial
    reportes: ServicioReportes
    prediccion: ServicioPrediccion
    sincronizacion: ServicioSincronizacion

    def cerrar(self) -> None:
        self.conexiones.cerrar()


def crear_aplicacion() -> Aplicacion:
    config = cargar_config()
    configurar_logs(config.log_archivo)
    conexiones = Conexiones(config)

    relacional = RepositorioRelacional(conexiones)
    documental = RepositorioDocumental(conexiones)
    grafo = RepositorioGrafo(conexiones)
    clave_valor = RepositorioClaveValor(conexiones)

    sincronizacion = ServicioSincronizacion(relacional, documental, grafo)
    trazabilidad = ServicioTrazabilidad(relacional, documental, grafo, sincronizacion)
    return Aplicacion(
        config=config,
        conexiones=conexiones,
        auth=ServicioAuth(relacional, clave_valor, config.sesion_ttl_segundos),
        operativa=ServicioOperativa(relacional, documental, sincronizacion),
        monitoreo=ServicioMonitoreo(relacional, documental, clave_valor, trazabilidad, config),
        trazabilidad=trazabilidad,
        mensajeria=ServicioMensajeria(relacional, documental),
        comercial=ServicioComercial(relacional, documental, config.margen_facturacion),
        reportes=ServicioReportes(documental, grafo, config.directorio_salidas),
        prediccion=ServicioPrediccion(documental, ClimaSinFuenteDeDatos()),
        sincronizacion=sincronizacion,
    )
