from contextlib import contextmanager
from datetime import datetime
from typing import Callable, Iterator, TypeVar

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.client_session import ClientSession
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError, WriteError

from app.dominio.reglas import ESTADOS_CERRADOS, dias_entre, ruta
from app.infra.conexiones import Conexiones
from app.infra.errores import IntegridadError, NoEncontrado

CODIGO_VALIDACION_FALLIDA = 121
CERRADOS = sorted(ESTADOS_CERRADOS)
AGRUPACIONES_DE_ENVIOS = {"pais": "$destino.pais", "estado": "$estado", "cliente": "$cliente.id"}
ULTIMO_MENSAJE_POR_CONVERSACION = {
    "_id": "$conversacion_id", "mensajes": {"$sum": 1}, "fecha_hora": {"$first": "$fecha_hora"},
    "contenido": {"$first": "$contenido"}, "participantes": {"$first": "$participantes"},
}

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


def _renombrar_id(fila: dict, nombre: str | None) -> dict:
    valor = fila.pop("_id")
    return fila if nombre is None else {nombre: valor, **fila}


def _nombrar_grupo(fila: dict, agrupacion: str) -> dict:
    return _renombrar_id(fila, "cliente_id" if agrupacion == "cliente" else agrupacion)


def _redondear(fila: dict, *campos: str) -> dict:
    for campo in campos:
        if fila.get(campo) is not None:
            fila[campo] = round(fila[campo], 2)
    return fila


def _con_porcentaje_a_tiempo(fila: dict) -> dict:
    fila["a_tiempo"] = fila["entregados"] - fila["demorados"]
    fila["porcentaje_a_tiempo"] = round(fila["a_tiempo"] / fila["entregados"] * 100, 1)
    return fila


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

    def listar_envios(self, cliente_id: int | None = None, pais_destino: str | None = None) -> list[dict]:
        filtro = {}
        if cliente_id is not None:
            filtro["cliente.id"] = cliente_id
        if pais_destino is not None:
            filtro["destino.pais"] = pais_destino
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
                       metricas_de_entrega: dict | None, sesion: ClientSession) -> bool:
        cambios = {"ultimo_evento": ultimo_evento}
        if nuevo_estado is not None:
            cambios.update(estado=nuevo_estado, grafo_sincronizado=False)
        if metricas_de_entrega is not None:
            cambios.update(fecha_entrega_real=ultimo_evento["fecha_hora"], **metricas_de_entrega)
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

    def demoras_por_ruta(self) -> dict[str, tuple[int, float]]:
        filas = self._db.envios.aggregate([
            {"$match": {"estado": "ENTREGADO"}},
            {"$group": {"_id": {"origen": "$origen.codigo", "destino": "$destino.codigo"},
                        "entregados": {"$sum": 1}, "tasa_demora": {"$avg": "$demorado"}}},
        ])
        return {ruta(fila["_id"]["origen"], fila["_id"]["destino"]): (fila["entregados"], fila["tasa_demora"] or 0.0)
                for fila in filas}

    # Eventos

    def insertar_evento(self, evento: dict, sesion: ClientSession) -> None:
        self._db.eventos.insert_one(evento, session=sesion)

    def eventos_de_envio(self, envio_id: int) -> list[dict]:
        return list(self._db.eventos.find({"envio_id": envio_id}).sort("fecha_hora", ASCENDING))

    def eventos_de_contenedor(self, contenedor_id: int) -> list[dict]:
        return list(self._db.eventos.find({"contenedor_ids": contenedor_id}).sort("fecha_hora", ASCENDING))

    # Lecturas

    def insertar_lectura(self, lectura: dict) -> ObjectId:
        with _traducir_errores():
            return self._db.lecturas.insert_one(lectura).inserted_id

    def lecturas_de_sensor(self, sensor_id: int, desde: datetime, hasta: datetime) -> list[dict]:
        filtro = {"sensor_id": sensor_id, **_rango("fecha_hora", desde, hasta)}
        return list(self._db.lecturas.find(filtro, {"_id": 0}).sort("fecha_hora", ASCENDING))

    def posiciones_de_contenedor(self, contenedor_id: int) -> list[dict]:
        return list(self._db.lecturas.find(
            {"contenedor_id": contenedor_id, "lat": {"$ne": None}},
            {"_id": 0, "fecha_hora": 1, "lat": 1, "lon": 1, "sensor_id": 1, "temperatura": 1},
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
            {"$group": ULTIMO_MENSAJE_POR_CONVERSACION},
            {"$sort": {"fecha_hora": DESCENDING}},
        ]))

    def resumen_conversaciones(self, conversacion_ids: list[str]) -> list[dict]:
        return list(self._db.mensajes.aggregate([
            {"$match": {"conversacion_id": {"$in": conversacion_ids}}},
            {"$sort": {"fecha_hora": DESCENDING}},
            {"$group": ULTIMO_MENSAJE_POR_CONVERSACION},
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
        grupo = {"_id": AGRUPACIONES_DE_ENVIOS[agrupacion], "cantidad": {"$sum": 1}}
        if agrupacion == "cliente":
            grupo["cliente"] = {"$first": "$cliente.razon_social"}
        filas = self._db.envios.aggregate([
            {"$match": _filtro_envios(desde, hasta, cliente_id)},
            {"$group": grupo},
            {"$sort": {"cantidad": DESCENDING, "_id": ASCENDING}},
        ])
        return [_nombrar_grupo(fila, agrupacion) for fila in filas]

    def envios_demorados(self, ahora: datetime, desde, hasta, cliente_id) -> list[dict]:
        envios = self._db.envios.find({**_filtro_envios(desde, hasta, cliente_id), "$or": [
            {"estado": {"$nin": CERRADOS}, "fecha_entrega_estimada": {"$lt": ahora}},
            {"demorado": 1},
        ]}).sort("_id", ASCENDING)
        return [{"envio_id": envio["_id"], "cliente": envio["cliente"]["razon_social"], "estado": envio["estado"],
                 "fecha_entrega_estimada": envio["fecha_entrega_estimada"],
                 "fecha_entrega_real": envio["fecha_entrega_real"],
                 "dias_de_demora": dias_entre(envio["fecha_entrega_estimada"], envio["fecha_entrega_real"] or ahora)}
                for envio in envios]

    def _entregados(self, desde, hasta, cliente_id) -> dict:
        return {"$match": {**_filtro_envios(desde, hasta, cliente_id, "fecha_entrega_real"), "estado": "ENTREGADO"}}

    def tiempos_de_envio_por_cliente(self, desde, hasta, cliente_id) -> list[dict]:
        filas = self._db.envios.aggregate([
            self._entregados(desde, hasta, cliente_id),
            {"$group": {"_id": "$cliente.id", "cliente": {"$first": "$cliente.razon_social"},
                        "entregados": {"$sum": 1}, "dias_maximo": {"$max": "$dias_entrega"},
                        "dias_minimo": {"$min": "$dias_entrega"}, "dias_promedio": {"$avg": "$dias_entrega"}}},
            {"$sort": {"_id": ASCENDING}},
        ])
        return [_redondear(_renombrar_id(fila, "cliente_id"), "dias_maximo", "dias_minimo", "dias_promedio")
                for fila in filas]

    def tiempo_promedio_de_entrega(self, desde, hasta, cliente_id) -> list[dict]:
        filas = self._db.envios.aggregate([
            self._entregados(desde, hasta, cliente_id),
            {"$group": {"_id": None, "entregados": {"$sum": 1}, "dias_promedio": {"$avg": "$dias_entrega"}}},
        ])
        return [_redondear(_renombrar_id(fila, None), "dias_promedio") for fila in filas]

    def promedio_de_incidentes(self, agrupacion: str, desde, hasta, cliente_id) -> list[dict]:
        grupo = {"_id": AGRUPACIONES_DE_ENVIOS[agrupacion], "envios": {"$sum": 1},
                 "incidentes": {"$sum": "$cantidad_incidentes"}, "promedio": {"$avg": "$cantidad_incidentes"}}
        if agrupacion == "cliente":
            grupo["cliente"] = {"$first": "$cliente.razon_social"}
        filas = self._db.envios.aggregate([
            {"$match": _filtro_envios(desde, hasta, cliente_id)},
            {"$group": grupo},
            {"$sort": {"promedio": DESCENDING, "_id": ASCENDING}},
        ])
        return [_redondear(_nombrar_grupo(fila, agrupacion), "promedio") for fila in filas]

    def costos_por_transporte(self, desde, hasta, cliente_id) -> list[dict]:
        filas = self._db.envios.aggregate([
            {"$match": _filtro_envios(desde, hasta, cliente_id)},
            {"$unwind": "$tramos"},
            {"$group": {"_id": "$tramos.medio", "tramos": {"$sum": 1}, "costo_total": {"$sum": "$tramos.costo"},
                        "costo_promedio": {"$avg": "$tramos.costo"}}},
            {"$sort": {"costo_total": DESCENDING}},
        ])
        return [_redondear(_renombrar_id(fila, "medio"), "costo_total", "costo_promedio") for fila in filas]

    def ranking_rutas_por_incidentes(self, desde, hasta, envio_ids: list[int] | None) -> list[dict]:
        filtro = _rango("fecha", desde, hasta)
        if envio_ids is not None:
            filtro["envio_id"] = {"$in": envio_ids}
        por_ruta = [{"$group": {"_id": "$ruta", "incidentes": {"$sum": 1}}},
                    {"$sort": {"incidentes": DESCENDING, "_id": ASCENDING}}]
        totales = self._db.incidentes.aggregate([{"$match": filtro}, *por_ruta])
        abiertos = {fila["_id"]: fila["incidentes"]
                    for fila in self._db.incidentes.aggregate([{"$match": {**filtro, "estado": "ABIERTO"}}, *por_ruta])}
        filas = [_renombrar_id(fila, "ruta") for fila in totales]
        return [{**fila, "abiertos": abiertos.get(fila["ruta"], 0)} for fila in filas]

    def ranking_clientes_por_volumen(self, desde, hasta, cliente_id) -> list[dict]:
        filas = self._db.envios.aggregate([
            {"$match": {**_filtro_envios(desde, hasta, cliente_id), "estado": {"$ne": "CANCELADO"}}},
            {"$group": {"_id": "$cliente.id", "cliente": {"$first": "$cliente.razon_social"}, "envios": {"$sum": 1},
                        "volumen_m3": {"$sum": "$volumen_m3"}, "peso_kg": {"$sum": "$peso_kg"}}},
            {"$sort": {"volumen_m3": DESCENDING, "peso_kg": DESCENDING}},
        ])
        return [_renombrar_id(fila, "cliente_id") for fila in filas]

    def desempeno_mensual(self, desde, hasta, cliente_id) -> list[dict]:
        filas = self._db.envios.aggregate([
            self._entregados(desde, hasta, cliente_id),
            {"$group": {"_id": "$mes_entrega", "entregados": {"$sum": 1}, "demorados": {"$sum": "$demorado"}}},
            {"$sort": {"_id": ASCENDING}},
        ])
        return [_con_porcentaje_a_tiempo(_renombrar_id(fila, "mes")) for fila in filas]

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
