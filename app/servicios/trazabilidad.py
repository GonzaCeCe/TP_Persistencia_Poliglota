import logging
from datetime import datetime

from app.dominio import reglas
from app.infra.errores import ErrorNegocio
from app.repositorios.documental import RepositorioDocumental
from app.repositorios.grafo import RepositorioGrafo
from app.repositorios.relacional import RepositorioRelacional
from app.servicios.auth import NIVEL_OPERADOR, SesionActiva, requerir_nivel, verificar_acceso_a_envio
from app.servicios.sincronizacion import ServicioSincronizacion

log = logging.getLogger(__name__)

SEVERIDADES = ("BAJA", "MEDIA", "ALTA", "CRITICA")


def _a_milisegundos(momento: datetime) -> datetime:
    return momento.replace(microsecond=momento.microsecond // 1000 * 1000)


class ServicioTrazabilidad:
    def __init__(self, relacional: RepositorioRelacional, documental: RepositorioDocumental,
                 grafo: RepositorioGrafo, sincronizacion: ServicioSincronizacion):
        self._rel = relacional
        self._doc = documental
        self._grafo = grafo
        self._sync = sincronizacion

    def _envio_visible(self, sesion: SesionActiva, envio_id: int) -> dict:
        envio = self._doc.obtener_envio(envio_id)
        verificar_acceso_a_envio(sesion, envio)
        return envio

    # Eventos logísticos

    def registrar_evento(self, sesion: SesionActiva, envio_id: int, tipo: str, ubicacion: str,
                         descripcion: str = "", fecha_hora: datetime | None = None) -> dict:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        envio = self._doc.obtener_envio(envio_id)
        nuevo_estado = reglas.estado_tras_evento(tipo)
        momento = _a_milisegundos(fecha_hora or reglas.ahora_utc())
        self._validar_evento(envio, tipo, momento)
        evento = {"envio_id": envio_id, "contenedor_ids": [c["id"] for c in envio["contenedores"]],
                  "fecha_hora": momento, "tipo": tipo, "ubicacion": ubicacion.strip(), "descripcion": descripcion.strip()}
        ultimo_evento = {"tipo": tipo, "fecha_hora": momento, "ubicacion": evento["ubicacion"]}
        metricas = None
        if nuevo_estado == "ENTREGADO":
            metricas = reglas.metricas_de_entrega(envio["fecha_creacion"], envio["fecha_entrega_estimada"], momento)
        es_nuevo = self._doc.insertar_evento(evento)
        if not es_nuevo:
            log.info("Evento %s del envío %s en %s ya registrado: reintento, no se duplica", tipo, envio_id, momento)
        avanzo = self._doc.aplicar_evento(envio_id, ultimo_evento, nuevo_estado, metricas)
        actual = self._doc.obtener_envio(envio_id)
        es_el_ultimo = (actual["ultimo_evento"]["tipo"], actual["ultimo_evento"]["fecha_hora"]) == (tipo, momento)
        if es_el_ultimo and nuevo_estado == "ENTREGADO":
            self._liberar_contenedores(actual)
        if es_el_ultimo and nuevo_estado is not None:
            self._sync.proyectar_envio(envio_id)
        log.info("Evento %s registrado en el envío %s (%s)", tipo, envio_id,
                 "estado actualizado" if avanzo else "sin cambio de estado")
        return {"duplicado": not es_nuevo, "estado_actualizado": avanzo, "estado": actual["estado"]}

    def _liberar_contenedores(self, envio: dict) -> None:
        libres = [c["id"] for c in envio["contenedores"] if self._doc.envio_activo_con_contenedor(c["id"]) is None]
        if libres:
            self._rel.cambiar_estado_contenedores(libres, "DISPONIBLE", "EN_USO")

    def _validar_evento(self, envio: dict, tipo: str, momento: datetime) -> None:
        if envio["estado"] == "CANCELADO":
            raise ErrorNegocio("El envío está cancelado")
        if momento < envio["fecha_creacion"]:
            raise ErrorNegocio("El evento no puede ser anterior a la creación del envío")
        if envio["estado"] == "ENTREGADO" and momento > envio["fecha_entrega_real"]:
            raise ErrorNegocio("El envío ya fue entregado; solo se aceptan eventos anteriores a la entrega")
        if tipo == "ENTREGADO" and not envio["tramos"]:
            raise ErrorNegocio("No se puede entregar un envío sin tramos")

    def historial_eventos(self, sesion: SesionActiva, envio_id: int) -> list[dict]:
        self._envio_visible(sesion, envio_id)
        return self._doc.eventos_de_envio(envio_id)

    def seguimiento_envio(self, sesion: SesionActiva, envio_id: int) -> dict:
        envio = self._envio_visible(sesion, envio_id)
        linea_de_tiempo = [(envio["fecha_creacion"], "CREACION", f"Envío creado ({envio['prioridad']})")]
        for tramo in envio["tramos"]:
            recorrido = f"{tramo['origen']['codigo']} -> {tramo['destino']['codigo']} ({tramo['medio']})"
            linea_de_tiempo.append((tramo["fecha_salida"], "SALIDA TRAMO", recorrido))
            linea_de_tiempo.append((tramo["fecha_llegada_estimada"], "LLEGADA ESTIMADA", recorrido))
        for evento in self._doc.eventos_de_envio(envio_id):
            linea_de_tiempo.append((evento["fecha_hora"], f"EVENTO {evento['tipo']}",
                                    f"{evento['ubicacion']} {evento['descripcion']}".strip()))
        for incidente in self._doc.incidentes_de_envio(envio_id):
            linea_de_tiempo.append((incidente["fecha"], f"INCIDENTE {incidente['severidad']}", incidente["descripcion"]))
            if incidente["fecha_cierre"] is not None:
                linea_de_tiempo.append((incidente["fecha_cierre"], "INCIDENTE CERRADO", f"Incidente {incidente['_id']}"))
        demorado = reglas.envio_demorado(envio["estado"], envio["fecha_entrega_estimada"],
                                         envio["fecha_entrega_real"], reglas.ahora_utc())
        return {"envio": envio, "demorado": demorado,
                "linea_de_tiempo": [{"fecha": f, "hito": h, "detalle": d} for f, h, d in sorted(linea_de_tiempo, key=lambda x: x[0])]}

    # Contenedores

    def recorrido_contenedor(self, sesion: SesionActiva, contenedor_id: int) -> dict:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        contenedor = self._rel.obtener_contenedor(contenedor_id)
        return {"contenedor": contenedor, "posiciones": self._doc.posiciones_de_contenedor(contenedor_id)}

    def movimientos_contenedor(self, sesion: SesionActiva, contenedor_id: int) -> dict:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        contenedor = self._rel.obtener_contenedor(contenedor_id)
        return {"contenedor": contenedor,
                "envios": self._doc.envios_de_contenedor(contenedor_id),
                "eventos": self._doc.eventos_de_contenedor(contenedor_id)}

    # Incidentes y alertas

    def registrar_incidente(self, sesion: SesionActiva, envio_id: int, tipo: str, severidad: str,
                            descripcion: str, fecha: datetime | None = None) -> int:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        if severidad not in SEVERIDADES:
            raise ErrorNegocio(f"Severidad inválida: {severidad}")
        envio = self._doc.obtener_envio(envio_id)
        momento = fecha or reglas.ahora_utc()
        if momento < envio["fecha_creacion"]:
            raise ErrorNegocio("El incidente no puede ser anterior a la creación del envío")
        return self._crear_incidente(envio, tipo.strip().upper(), severidad, descripcion.strip(), momento)

    def registrar_incidente_automatico(self, envio: dict, tipo: str, descripcion: str, fecha: datetime) -> int:
        return self._crear_incidente(envio, tipo, "ALTA", descripcion, fecha)

    def _crear_incidente(self, envio: dict, tipo: str, severidad: str, descripcion: str, fecha: datetime) -> int:
        tramo = reglas.tramo_vigente(envio["tramos"], fecha)
        incidente = {
            "_id": self._doc.siguiente_id("incidentes"),
            "envio_id": envio["_id"],
            "tramo_id": tramo["id"] if tramo else None,
            "ruta": reglas.ruta(envio["origen"]["codigo"], envio["destino"]["codigo"]),
            "tipo": tipo,
            "fecha": fecha,
            "severidad": severidad,
            "estado": "ABIERTO",
            "descripcion": descripcion,
            "fecha_cierre": None,
        }
        self._doc.insertar_incidente(incidente)
        self._doc.incrementar_incidentes(envio["_id"])
        log.info("Incidente %s (%s, %s) en el envío %s, tramo %s", incidente["_id"], tipo, severidad,
                 envio["_id"], incidente["tramo_id"])
        return incidente["_id"]

    def cerrar_incidente(self, sesion: SesionActiva, incidente_id: int, fecha: datetime | None = None) -> None:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        incidente = self._doc.obtener_incidente(incidente_id)
        momento = fecha or reglas.ahora_utc()
        if momento < incidente["fecha"]:
            raise ErrorNegocio("El cierre no puede ser anterior a la apertura del incidente")
        if not self._doc.cerrar_incidente(incidente_id, momento):
            raise ErrorNegocio(f"El incidente {incidente_id} ya está cerrado")
        log.info("Incidente %s cerrado por el usuario %s", incidente_id, sesion.usuario_id)

    def cerrar_alerta(self, sesion: SesionActiva, alerta_id: int) -> None:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        self._doc.obtener_alerta(alerta_id)
        if not self._doc.cerrar_alerta(alerta_id, reglas.ahora_utc()):
            raise ErrorNegocio(f"La alerta {alerta_id} ya está cerrada")
        log.info("Alerta %s cerrada por el usuario %s", alerta_id, sesion.usuario_id)

    def incidentes_abiertos(self, sesion: SesionActiva) -> list[dict]:
        envio_ids = None if sesion.cliente_id is None else self._doc.envio_ids_de_cliente(sesion.cliente_id)
        return self._doc.incidentes_abiertos(envio_ids=envio_ids)

    def alertas_abiertas(self, sesion: SesionActiva) -> list[dict]:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        return self._doc.alertas_abiertas()

    # Consultas sobre el grafo

    def ruta_completa(self, sesion: SesionActiva, envio_id: int) -> dict:
        envio = self._envio_visible(sesion, envio_id)
        return {"tramos": self._grafo.ruta_completa(envio_id), "grafo_sincronizado": envio["grafo_sincronizado"]}

    def red_de_relaciones(self, sesion: SesionActiva) -> dict:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        return {"red": self._grafo.red_clientes_operadores(),
                "comparten_operador": self._grafo.clientes_que_comparten_operador()}

    def impacto_de_ubicacion(self, sesion: SesionActiva, codigo: str) -> list[dict]:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        return self._grafo.impacto_de_ubicacion(codigo.strip().upper())
