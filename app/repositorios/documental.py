from contextlib import contextmanager
from datetime import datetime
from typing import Callable, Iterator, TypeVar

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.client_session import ClientSession
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError, WriteError

from app.dominio.reglas import ESTADOS_CERRADOS
from app.infra.conexiones import Conexiones
from app.infra.errores import IntegridadError, NoEncontrado

CODIGO_VALIDACION_FALLIDA = 121
CERRADOS = sorted(ESTADOS_CERRADOS)
AGRUPACIONES_DE_ENVIOS = {"pais": "$destino.pais", "estado": "$estado", "cliente": "$cliente.id"}
RUTA_DEL_ENVIO = {"$concat": ["$origen.codigo", "-", "$destino.codigo"]}
ENTREGA_TARDIA = {"$gt": ["$fecha_entrega_real", "$fecha_entrega_estimada"]}

T = TypeVar("T")


@contextmanager
def _traducir_errores() -> Iterator[None]:
    try:
        yield
    except DuplicateKeyError as error:
        clave = (error.details or {}).get("keyValue", {})
        raise IntegridadError(f"Registro duplicado: {clave}") from error
    except WriteError as error:
        if error.code == CODIGO_VALIDACION_FALLIDA:
            raise IntegridadError("El documento no cumple el esquema de la colección") from error
        raise


def _rango(campo: str, desde: datetime | None, hasta: datetime | None) -> dict:
    condicion = {}
    if desde is not None:
        condicion["$gte"] = desde
    if hasta is not None:
        condicion["$lt"] = hasta
    return {campo: condicion} if condicion else {}


def _nombrar_grupo(agrupacion: str) -> list[dict]:
    if agrupacion == "cliente":
        return [{"$set": {"cliente_id": "$_id"}}]
    return [{"$set": {agrupacion: "$_id"}}, {"$unset": "cliente"}]


def _filtro_envios(desde: datetime | None, hasta: datetime | None, cliente_id: int | None,
                   campo_fecha: str = "fecha_creacion") -> dict:
    filtro = _rango(campo_fecha, desde, hasta)
    if cliente_id is not None:
        filtro["cliente.id"] = cliente_id
    return filtro


class RepositorioDocumental:
    def __init__(self, conexiones: Conexiones):
        self._conexiones = conexiones

    @property
    def _db(self) -> Database:
        return self._conexiones.mongo()

    def en_transaccion(self, operacion: Callable[[ClientSession], T]) -> T:
        with _traducir_errores(), self._conexiones.mongo_cliente().start_session() as sesion:
            return sesion.with_transaction(operacion)

    def siguiente_id(self, secuencia: str) -> int:
        contador = self._db.contadores.find_one_and_update(
            {"_id": secuencia}, {"$inc": {"valor": 1}}, upsert=True, return_document=ReturnDocument.AFTER)
        return contador["valor"]

    def _obtener(self, coleccion: str, id_, descripcion: str) -> dict:
        documento = self._db[coleccion].find_one({"_id": id_})
        if documento is None:
            raise NoEncontrado(f"{descripcion} {id_} no existe")
        return documento

    # Envíos

    def insertar_envio(self, envio: dict) -> None:
        with _traducir_errores():
            self._db.envios.insert_one(envio)

    def borrar_envio(self, envio_id: int) -> None:
        self._db.envios.delete_one({"_id": envio_id})

    def obtener_envio(self, envio_id: int) -> dict:
        return self._obtener("envios", envio_id, "Envío")

    def listar_envios(self, cliente_id: int | None = None) -> list[dict]:
        filtro = {} if cliente_id is None else {"cliente.id": cliente_id}
        return list(self._db.envios.find(filtro).sort("_id", ASCENDING))

    def envio_ids_de_cliente(self, cliente_id: int) -> list[int]:
        return [envio["_id"] for envio in self._db.envios.find({"cliente.id": cliente_id}, {"_id": 1})]

    def contar_envios_activos_de_cliente(self, cliente_id: int) -> int:
        return self._db.envios.count_documents({"cliente.id": cliente_id, "estado": {"$nin": CERRADOS}})

    def agregar_tramo(self, envio_id: int, tramo: dict, tramos_previos: int,
                      fecha_entrega_estimada: datetime) -> bool:
        with _traducir_errores():
            resultado = self._db.envios.update_one(
                {"_id": envio_id, "tramos": {"$size": tramos_previos}},
                {"$push": {"tramos": tramo},
                 "$set": {"fecha_entrega_estimada": fecha_entrega_estimada, "grafo_sincronizado": False}})
        return resultado.modified_count == 1

    def aplicar_evento(self, envio_id: int, ultimo_evento: dict, nuevo_estado: str | None,
                       sesion: ClientSession) -> bool:
        cambios = {"ultimo_evento": ultimo_evento}
        if nuevo_estado is not None:
            cambios.update(estado=nuevo_estado, grafo_sincronizado=False)
        if nuevo_estado == "ENTREGADO":
            cambios["fecha_entrega_real"] = ultimo_evento["fecha_hora"]
        resultado = self._db.envios.update_one(
            {"_id": envio_id, "$or": [{"ultimo_evento": None},
                                      {"ultimo_evento.fecha_hora": {"$lt": ultimo_evento["fecha_hora"]}}]},
            {"$set": cambios}, session=sesion)
        return resultado.modified_count == 1

    def cancelar_envio(self, envio_id: int) -> bool:
        resultado = self._db.envios.update_one(
            {"_id": envio_id, "estado": "CREADO"},
            {"$set": {"estado": "CANCELADO", "grafo_sincronizado": False}})
        return resultado.modified_count == 1

    def incrementar_incidentes(self, envio_id: int, sesion: ClientSession) -> None:
        self._db.envios.update_one({"_id": envio_id}, {"$inc": {"cantidad_incidentes": 1}}, session=sesion)

    def envio_activo_con_contenedor(self, contenedor_id: int) -> dict | None:
        return self._db.envios.find_one({"contenedores.id": contenedor_id, "estado": {"$nin": CERRADOS}})

    def envios_activos(self) -> list[dict]:
        return list(self._db.envios.find({"estado": {"$nin": CERRADOS}}).sort("_id", ASCENDING))

    def envios_de_contenedor(self, contenedor_id: int) -> list[dict]:
        return list(self._db.envios.find({"contenedores.id": contenedor_id}).sort("fecha_creacion", ASCENDING))

    def envios_para_facturar(self, fin_periodo: datetime) -> list[dict]:
        return list(self._db.envios.find(
            {"facturado": False, "estado": "ENTREGADO", "fecha_entrega_real": {"$lt": fin_periodo}}
        ).sort("_id", ASCENDING))

    def marcar_facturados(self, envio_ids: list[int], factura_id: int) -> None:
        self._db.envios.update_many({"_id": {"$in": envio_ids}},
                                    {"$set": {"facturado": True, "factura_id": factura_id}})

    def envios_marcados_como_facturados(self) -> list[dict]:
        return list(self._db.envios.find({"facturado": True}, {"_id": 1, "factura_id": 1}))

    def envios_no_sincronizados(self) -> list[dict]:
        return list(self._db.envios.find({"grafo_sincronizado": False}).sort("_id", ASCENDING))

    def todos_los_envios(self) -> list[dict]:
        return list(self._db.envios.find().sort("_id", ASCENDING))

    def marcar_sincronizado(self, envio_id: int) -> None:
        self._db.envios.update_one({"_id": envio_id}, {"$set": {"grafo_sincronizado": True}})

    def demoras_por_ruta(self) -> dict[str, tuple[int, int]]:
        filas = self._db.envios.aggregate([
            {"$match": {"estado": "ENTREGADO"}},
            {"$group": {"_id": RUTA_DEL_ENVIO, "entregados": {"$sum": 1},
                        "demorados": {"$sum": {"$cond": [ENTREGA_TARDIA, 1, 0]}}}},
        ])
        return {fila["_id"]: (fila["entregados"], fila["demorados"]) for fila in filas}

    # Eventos

    def insertar_evento(self, evento: dict, sesion: ClientSession) -> None:
        self._db.eventos.insert_one(evento, session=sesion)

    def eventos_de_envio(self, envio_id: int) -> list[dict]:
        return list(self._db.eventos.find({"envio_id": envio_id}).sort("fecha_hora", ASCENDING))

    def eventos_de_contenedor(self, contenedor_id: int) -> list[dict]:
        return list(self._db.eventos.find({"contenedor_ids": contenedor_id}).sort("fecha_hora", ASCENDING))

    # Lecturas

    def insertar_lectura(self, lectura: dict) -> ObjectId:
        return self._db.lecturas.insert_one(lectura).inserted_id

    def lecturas_de_sensor(self, sensor_id: int, desde: datetime, hasta: datetime) -> list[dict]:
        filtro = {"meta.sensor_id": sensor_id, **_rango("fecha_hora", desde, hasta)}
        return list(self._db.lecturas.find(filtro, {"_id": 0}).sort("fecha_hora", ASCENDING))

    def posiciones_de_contenedor(self, contenedor_id: int) -> list[dict]:
        return list(self._db.lecturas.find(
            {"meta.contenedor_id": contenedor_id, "lat": {"$ne": None}},
            {"_id": 0, "fecha_hora": 1, "lat": 1, "lon": 1, "meta": 1, "temperatura": 1},
        ).sort("fecha_hora", ASCENDING))

    # Incidentes

    def insertar_incidente(self, incidente: dict, sesion: ClientSession) -> None:
        self._db.incidentes.insert_one(incidente, session=sesion)

    def obtener_incidente(self, incidente_id: int) -> dict:
        return self._obtener("incidentes", incidente_id, "Incidente")

    def cerrar_incidente(self, incidente_id: int, fecha_cierre: datetime) -> bool:
        resultado = self._db.incidentes.update_one(
            {"_id": incidente_id, "estado": "ABIERTO"},
            {"$set": {"estado": "CERRADO", "fecha_cierre": fecha_cierre}})
        return resultado.modified_count == 1

    def incidentes_de_envio(self, envio_id: int) -> list[dict]:
        return list(self._db.incidentes.find({"envio_id": envio_id}).sort("fecha", ASCENDING))

    def incidentes_abiertos(self, desde: datetime | None = None, hasta: datetime | None = None,
                            envio_ids: list[int] | None = None) -> list[dict]:
        filtro = {"estado": "ABIERTO", **_rango("fecha", desde, hasta)}
        if envio_ids is not None:
            filtro["envio_id"] = {"$in": envio_ids}
        return list(self._db.incidentes.find(filtro).sort("fecha", ASCENDING))

    def incidentes_abiertos_por_envio(self) -> dict[int, int]:
        filas = self._db.incidentes.aggregate([
            {"$match": {"estado": "ABIERTO"}},
            {"$group": {"_id": "$envio_id", "cantidad": {"$sum": 1}}},
        ])
        return {fila["_id"]: fila["cantidad"] for fila in filas}

    # Alertas

    def insertar_alerta(self, alerta: dict) -> bool:
        try:
            self._db.alertas.insert_one(alerta)
        except DuplicateKeyError:
            return False
        return True

    def obtener_alerta(self, alerta_id: int) -> dict:
        return self._obtener("alertas", alerta_id, "Alerta")

    def cerrar_alerta(self, alerta_id: int, fecha_cierre: datetime) -> bool:
        resultado = self._db.alertas.update_one(
            {"_id": alerta_id, "estado": "ABIERTA"},
            {"$set": {"estado": "CERRADA", "fecha_cierre": fecha_cierre}})
        return resultado.modified_count == 1

    def cerrar_alertas_de_sensor(self, sensor_id: int, tipo: str, fecha_cierre: datetime) -> int:
        resultado = self._db.alertas.update_many(
            {"sensor_id": sensor_id, "tipo": tipo, "estado": "ABIERTA"},
            {"$set": {"estado": "CERRADA", "fecha_cierre": fecha_cierre}})
        return resultado.modified_count

    def alertas_abiertas(self) -> list[dict]:
        return list(self._db.alertas.find({"estado": "ABIERTA"}).sort("fecha", ASCENDING))

    def alertas_abiertas_por_contenedor(self) -> dict[int, int]:
        filas = self._db.alertas.aggregate([
            {"$match": {"estado": "ABIERTA", "contenedor_id": {"$ne": None}}},
            {"$group": {"_id": "$contenedor_id", "cantidad": {"$sum": 1}}},
        ])
        return {fila["_id"]: fila["cantidad"] for fila in filas}

    # Mensajes y grupos

    def insertar_mensaje(self, mensaje: dict) -> None:
        with _traducir_errores():
            self._db.mensajes.insert_one(mensaje)

    def mensajes_de_conversacion(self, conversacion_id: str) -> list[dict]:
        return list(self._db.mensajes.find({"conversacion_id": conversacion_id}).sort("fecha_hora", ASCENDING))

    def resumen_conversaciones_privadas(self, usuario_id: int) -> list[dict]:
        return list(self._db.mensajes.aggregate([
            {"$match": {"participantes": usuario_id}},
            {"$sort": {"fecha_hora": DESCENDING}},
            {"$group": {"_id": "$conversacion_id", "ultimo": {"$first": "$$ROOT"}, "mensajes": {"$sum": 1}}},
            {"$sort": {"ultimo.fecha_hora": DESCENDING}},
        ]))

    def resumen_conversaciones(self, conversacion_ids: list[str]) -> list[dict]:
        return list(self._db.mensajes.aggregate([
            {"$match": {"conversacion_id": {"$in": conversacion_ids}}},
            {"$sort": {"fecha_hora": DESCENDING}},
            {"$group": {"_id": "$conversacion_id", "ultimo": {"$first": "$$ROOT"}, "mensajes": {"$sum": 1}}},
        ]))

    def insertar_grupo(self, grupo: dict) -> None:
        with _traducir_errores():
            self._db.grupos.insert_one(grupo)

    def obtener_grupo(self, grupo_id: int) -> dict:
        return self._obtener("grupos", grupo_id, "Grupo")

    def agregar_integrante(self, grupo_id: int, usuario_id: int) -> bool:
        resultado = self._db.grupos.update_one(
            {"_id": grupo_id, "integrantes.usuario_id": {"$ne": usuario_id}},
            {"$push": {"integrantes": {"usuario_id": usuario_id}}})
        return resultado.modified_count == 1

    def grupos_de_usuario(self, usuario_id: int) -> list[dict]:
        return list(self._db.grupos.find({"integrantes.usuario_id": usuario_id}).sort("_id", ASCENDING))

    def grupos_publicos(self) -> list[dict]:
        return list(self._db.grupos.find({"publico": True}).sort("_id", ASCENDING))

    # Reportes

    def insertar_reporte(self, reporte: dict) -> None:
        with _traducir_errores():
            self._db.reportes.insert_one(reporte)

    def finalizar_reporte(self, reporte_id: int, estado: str, resultado: list[dict] | None) -> None:
        self._db.reportes.update_one({"_id": reporte_id}, {"$set": {"estado": estado, "resultado": resultado}})

    def envios_agrupados(self, agrupacion: str, desde, hasta, cliente_id) -> list[dict]:
        return list(self._db.envios.aggregate([
            {"$match": _filtro_envios(desde, hasta, cliente_id)},
            {"$group": {"_id": AGRUPACIONES_DE_ENVIOS[agrupacion], "cantidad": {"$sum": 1},
                        "cliente": {"$first": "$cliente.razon_social"}}},
            *_nombrar_grupo(agrupacion),
            {"$sort": {"cantidad": DESCENDING, "_id": ASCENDING}},
        ]))

    def envios_demorados(self, ahora: datetime, desde, hasta, cliente_id) -> list[dict]:
        return list(self._db.envios.aggregate([
            {"$match": {**_filtro_envios(desde, hasta, cliente_id), "$or": [
                {"estado": {"$nin": CERRADOS}, "fecha_entrega_estimada": {"$lt": ahora}},
                {"estado": "ENTREGADO", "$expr": ENTREGA_TARDIA},
            ]}},
            {"$project": {
                "_id": 0, "envio_id": "$_id", "cliente": "$cliente.razon_social", "estado": 1,
                "fecha_entrega_estimada": 1, "fecha_entrega_real": 1,
                "dias_de_demora": {"$round": [{"$divide": [{"$dateDiff": {
                    "startDate": "$fecha_entrega_estimada",
                    "endDate": {"$ifNull": ["$fecha_entrega_real", ahora]}, "unit": "hour"}}, 24]}, 1]},
            }},
            {"$sort": {"envio_id": ASCENDING}},
        ]))

    def _duraciones_de_entregados(self, desde, hasta, cliente_id) -> list[dict]:
        return [
            {"$match": {**_filtro_envios(desde, hasta, cliente_id, "fecha_entrega_real"), "estado": "ENTREGADO"}},
            {"$set": {"dias": {"$divide": [{"$dateDiff": {
                "startDate": "$fecha_creacion", "endDate": "$fecha_entrega_real", "unit": "hour"}}, 24]}}},
        ]

    def tiempos_de_envio_por_cliente(self, desde, hasta, cliente_id) -> list[dict]:
        return list(self._db.envios.aggregate([
            *self._duraciones_de_entregados(desde, hasta, cliente_id),
            {"$group": {"_id": "$cliente.id", "cliente": {"$first": "$cliente.razon_social"},
                        "entregados": {"$sum": 1}, "dias_maximo": {"$max": "$dias"},
                        "dias_minimo": {"$min": "$dias"}, "dias_promedio": {"$avg": "$dias"}}},
            {"$project": {"_id": 0, "cliente_id": "$_id", "cliente": 1, "entregados": 1,
                          "dias_maximo": {"$round": ["$dias_maximo", 2]},
                          "dias_minimo": {"$round": ["$dias_minimo", 2]},
                          "dias_promedio": {"$round": ["$dias_promedio", 2]}}},
            {"$sort": {"cliente_id": ASCENDING}},
        ]))

    def tiempo_promedio_de_entrega(self, desde, hasta, cliente_id) -> list[dict]:
        return list(self._db.envios.aggregate([
            *self._duraciones_de_entregados(desde, hasta, cliente_id),
            {"$group": {"_id": None, "entregados": {"$sum": 1}, "dias_promedio": {"$avg": "$dias"}}},
            {"$project": {"_id": 0, "entregados": 1, "dias_promedio": {"$round": ["$dias_promedio", 2]}}},
        ]))

    def promedio_de_incidentes(self, agrupacion: str, desde, hasta, cliente_id) -> list[dict]:
        return list(self._db.envios.aggregate([
            {"$match": _filtro_envios(desde, hasta, cliente_id)},
            {"$group": {"_id": AGRUPACIONES_DE_ENVIOS[agrupacion], "envios": {"$sum": 1},
                        "incidentes": {"$sum": "$cantidad_incidentes"},
                        "promedio": {"$avg": "$cantidad_incidentes"},
                        "cliente": {"$first": "$cliente.razon_social"}}},
            {"$set": {"promedio": {"$round": ["$promedio", 2]}}},
            *_nombrar_grupo(agrupacion),
            {"$sort": {"promedio": DESCENDING, "_id": ASCENDING}},
        ]))

    def costos_por_transporte(self, desde, hasta, cliente_id) -> list[dict]:
        return list(self._db.envios.aggregate([
            {"$match": _filtro_envios(desde, hasta, cliente_id)},
            {"$unwind": "$tramos"},
            {"$group": {"_id": "$tramos.medio", "tramos": {"$sum": 1}, "costo_total": {"$sum": "$tramos.costo"},
                        "costo_promedio": {"$avg": "$tramos.costo"}}},
            {"$project": {"_id": 0, "medio": "$_id", "tramos": 1, "costo_total": {"$round": ["$costo_total", 2]},
                          "costo_promedio": {"$round": ["$costo_promedio", 2]}}},
            {"$sort": {"costo_total": DESCENDING}},
        ]))

    def ranking_rutas_por_incidentes(self, desde, hasta, envio_ids: list[int] | None) -> list[dict]:
        filtro = _rango("fecha", desde, hasta)
        if envio_ids is not None:
            filtro["envio_id"] = {"$in": envio_ids}
        return list(self._db.incidentes.aggregate([
            {"$match": filtro},
            {"$group": {"_id": "$ruta", "incidentes": {"$sum": 1},
                        "abiertos": {"$sum": {"$cond": [{"$eq": ["$estado", "ABIERTO"]}, 1, 0]}}}},
            {"$project": {"_id": 0, "ruta": "$_id", "incidentes": 1, "abiertos": 1}},
            {"$sort": {"incidentes": DESCENDING, "ruta": ASCENDING}},
        ]))

    def ranking_clientes_por_volumen(self, desde, hasta, cliente_id) -> list[dict]:
        return list(self._db.envios.aggregate([
            {"$match": {**_filtro_envios(desde, hasta, cliente_id), "estado": {"$ne": "CANCELADO"}}},
            {"$group": {"_id": "$cliente.id", "cliente": {"$first": "$cliente.razon_social"}, "envios": {"$sum": 1},
                        "volumen_m3": {"$sum": "$volumen_m3"}, "peso_kg": {"$sum": "$peso_kg"}}},
            {"$project": {"_id": 0, "cliente_id": "$_id", "cliente": 1, "envios": 1, "volumen_m3": 1, "peso_kg": 1}},
            {"$sort": {"volumen_m3": DESCENDING, "peso_kg": DESCENDING}},
        ]))

    def desempeno_mensual(self, desde, hasta, cliente_id) -> list[dict]:
        return list(self._db.envios.aggregate([
            {"$match": {**_filtro_envios(desde, hasta, cliente_id, "fecha_entrega_real"), "estado": "ENTREGADO"}},
            {"$group": {"_id": {"$dateToString": {"format": "%Y-%m", "date": "$fecha_entrega_real"}},
                        "entregados": {"$sum": 1},
                        "a_tiempo": {"$sum": {"$cond": [ENTREGA_TARDIA, 0, 1]}}}},
            {"$project": {"_id": 0, "mes": "$_id", "entregados": 1, "a_tiempo": 1,
                          "porcentaje_a_tiempo": {"$round": [
                              {"$multiply": [{"$divide": ["$a_tiempo", "$entregados"]}, 100]}, 1]}}},
            {"$sort": {"mes": ASCENDING}},
        ]))

    # Predicciones

    def guardar_prediccion(self, prediccion: dict) -> None:
        nuevo_id = self.siguiente_id("predicciones")
        self._db.predicciones.update_one(
            {"envio_id": prediccion["envio_id"], "dia": prediccion["dia"]},
            {"$set": prediccion, "$setOnInsert": {"_id": nuevo_id}}, upsert=True)

    def predicciones_de_envio(self, envio_id: int) -> list[dict]:
        return list(self._db.predicciones.find({"envio_id": envio_id}).sort("dia", DESCENDING))

    def predicciones_del_dia(self, dia: str) -> list[dict]:
        return list(self._db.predicciones.find({"dia": dia}).sort("probabilidad_demora", DESCENDING))
