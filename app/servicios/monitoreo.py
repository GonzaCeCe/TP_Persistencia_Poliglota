import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from redis.exceptions import RedisError

from app.config import Config
from app.dominio import reglas
from app.infra.errores import ErrorNegocio
from app.repositorios.clave_valor import RepositorioClaveValor
from app.repositorios.documental import RepositorioDocumental
from app.repositorios.relacional import RepositorioRelacional
from app.servicios.auth import NIVEL_ADMIN, NIVEL_OPERADOR, SesionActiva, requerir_nivel
from app.servicios.trazabilidad import ServicioTrazabilidad

log = logging.getLogger(__name__)


class ServicioMonitoreo:
    def __init__(self, relacional: RepositorioRelacional, documental: RepositorioDocumental,
                 clave_valor: RepositorioClaveValor, trazabilidad: ServicioTrazabilidad, config: Config):
        self._rel = relacional
        self._doc = documental
        self._kv = clave_valor
        self._traz = trazabilidad
        self._config = config

    # Lecturas

    def registrar_lectura(self, sensor_id: int, medidas: dict, fecha_hora: datetime | None = None) -> list[dict]:
        sensor = self._rel.obtener_sensor(sensor_id)
        if sensor["estado"] in ("BAJA", "FALLA"):
            raise ErrorNegocio(f"El sensor {sensor_id} está {sensor['estado']} y no acepta lecturas")
        if sensor["contenedor_id"] is None:
            raise ErrorNegocio(f"El sensor {sensor_id} no está asociado a ningún contenedor")
        valores = {nombre: float(medidas[nombre]) for nombre in reglas.MEDIDAS if medidas.get(nombre) is not None}
        reglas.validar_medidas(valores)
        momento = fecha_hora or reglas.ahora_utc()
        self._doc.insertar_lectura({"meta": {"sensor_id": sensor_id, "contenedor_id": sensor["contenedor_id"]},
                                    "fecha_hora": momento, **valores})
        self._actualizar_estado_en_vivo(sensor, valores, momento)
        if sensor["estado"] == "INACTIVO":
            self._reactivar_sensor(sensor_id, momento)
        return self._procesar_anomalias(sensor, valores, momento)

    def _actualizar_estado_en_vivo(self, sensor: dict, valores: dict, momento: datetime) -> None:
        self._kv.registrar_heartbeat(sensor["id"], reglas.ahora_utc().isoformat(), self._config.heartbeat_ttl_segundos)
        ultima = {"fecha_hora": momento.isoformat(), "contenedor_id": str(sensor["contenedor_id"]),
                  **{nombre: str(valor) for nombre, valor in valores.items()}}
        es_la_mas_reciente = self._kv.guardar_ultima_lectura(sensor["id"], ultima)
        if es_la_mas_reciente and "lat" in valores:
            self._kv.actualizar_posicion(sensor["contenedor_id"], valores["lon"], valores["lat"])

    def _reactivar_sensor(self, sensor_id: int, momento: datetime) -> None:
        if self._rel.cambiar_estado_sensor(sensor_id, "ACTIVO", "INACTIVO"):
            self._doc.cerrar_alertas_de_sensor(sensor_id, "SENSOR_INACTIVO", momento)
            log.info("Sensor %s reactivado al recibir una lectura", sensor_id)

    def _procesar_anomalias(self, sensor: dict, valores: dict, momento: datetime) -> list[dict]:
        anomalias = reglas.evaluar_lectura(valores.get("temperatura"), valores.get("bateria"),
                                           float(sensor["temp_min"]), float(sensor["temp_max"]),
                                           self._config.umbral_bateria)
        if not anomalias:
            return []
        envio = self._doc.envio_activo_con_contenedor(sensor["contenedor_id"])
        alertas = []
        for anomalia in anomalias:
            alerta = self._crear_alerta(sensor["id"], sensor["contenedor_id"], envio, anomalia.tipo, momento,
                                        "LECTURA", anomalia.valor, anomalia.umbral)
            if alerta is None:
                continue
            alertas.append(alerta)
            if anomalia.tipo == "TEMP_FUERA_RANGO" and envio is not None:
                alerta["incidente_id"] = self._traz.registrar_incidente_automatico(
                    envio, "TEMPERATURA",
                    f"Temperatura {anomalia.valor} °C fuera del rango del contenedor {sensor['codigo_internacional']} "
                    f"(umbral {anomalia.umbral} °C, sensor {sensor['id']})", momento)
        return alertas

    def _crear_alerta(self, sensor_id: int, contenedor_id: int | None, envio: dict | None, tipo: str,
                      momento: datetime, origen: str, valor: float | None, umbral: float | None) -> dict | None:
        alerta = {
            "_id": self._doc.siguiente_id("alertas"),
            "sensor_id": sensor_id,
            "contenedor_id": contenedor_id,
            "envio_id": envio["_id"] if envio else None,
            "evento": {"origen": origen, "fecha_hora": momento},
            "tipo": tipo,
            "fecha": momento,
            "estado": "ABIERTA",
            "valor": valor,
            "umbral": umbral,
            "fecha_cierre": None,
        }
        if not self._doc.insertar_alerta(alerta):
            log.info("Alerta %s del sensor %s ya estaba abierta: no se duplica", tipo, sensor_id)
            return None
        log.info("Alerta %s %s generada (sensor %s, contenedor %s, envío %s)", alerta["_id"], tipo, sensor_id,
                 contenedor_id, alerta["envio_id"])
        try:
            self._kv.publicar_alerta(alerta)
        except RedisError as error:
            log.warning("No se pudo publicar la alerta %s en Redis: %s", alerta["_id"], error)
        return alerta

    def historial_lecturas(self, sesion: SesionActiva, sensor_id: int, desde: datetime,
                           hasta: datetime) -> list[dict]:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        if desde >= hasta:
            raise ErrorNegocio("La fecha desde debe ser anterior a la fecha hasta")
        self._rel.obtener_sensor(sensor_id)
        return self._doc.lecturas_de_sensor(sensor_id, desde, hasta)

    # Visualización geográfica

    def exportar_recorrido_geojson(self, sesion: SesionActiva, contenedor_id: int) -> tuple[Path, int]:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        contenedor = self._rel.obtener_contenedor(contenedor_id)
        posiciones = self._doc.posiciones_de_contenedor(contenedor_id)
        if not posiciones:
            raise ErrorNegocio(f"El contenedor {contenedor['codigo_internacional']} no tiene posiciones GPS")
        self._config.directorio_salidas.mkdir(exist_ok=True)
        archivo = self._config.directorio_salidas / f"recorrido_contenedor_{contenedor_id}.geojson"
        archivo.write_text(json.dumps(_geojson(contenedor, posiciones), ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("Recorrido del contenedor %s exportado a %s", contenedor_id, archivo)
        return archivo, len(posiciones)

    def contenedores_cercanos(self, sesion: SesionActiva, lat: float, lon: float, radio_km: float) -> list[dict]:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        reglas.validar_medidas({"lat": lat, "lon": lon})
        if radio_km <= 0:
            raise ErrorNegocio("El radio debe ser mayor a cero")
        cercanos = self._kv.contenedores_en_radio(lon, lat, radio_km)
        codigos = {c["id"]: c["codigo_internacional"]
                   for c in self._rel.listar_contenedores([contenedor_id for contenedor_id, _ in cercanos])}
        return [{"contenedor_id": contenedor_id, "codigo": codigos.get(contenedor_id), "distancia_km": distancia}
                for contenedor_id, distancia in cercanos]

    # Estado de sensores

    def estado_sensores(self, sesion: SesionActiva) -> list[dict]:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        return [{**sensor, "reportando": self._kv.tiene_heartbeat(sensor["id"]),
                 "ultima_lectura": self._kv.ultima_lectura(sensor["id"])}
                for sensor in self._rel.listar_sensores()]

    def detectar_sensores_inactivos(self, sesion: SesionActiva) -> list[dict]:
        requerir_nivel(sesion, NIVEL_ADMIN)
        ahora = reglas.ahora_utc()
        limite = ahora - timedelta(minutes=self._config.minutos_gracia_sensor)
        inactivos = []
        for sensor in self._rel.sensores_activos_instalados_antes(limite):
            if self._kv.tiene_heartbeat(sensor["id"]) or not self._rel.cambiar_estado_sensor(sensor["id"], "INACTIVO", "ACTIVO"):
                continue
            envio = self._doc.envio_activo_con_contenedor(sensor["contenedor_id"]) if sensor["contenedor_id"] else None
            self._crear_alerta(sensor["id"], sensor["contenedor_id"], envio, "SENSOR_INACTIVO", ahora, "PROCESO", None, None)
            inactivos.append(sensor)
        log.info("Detección de sensores inactivos: %s pasaron a INACTIVO", len(inactivos))
        return inactivos

    def escuchar_alertas(self, sesion: SesionActiva) -> Iterator[dict]:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        return self._kv.escuchar_alertas()


def _geojson(contenedor: dict, posiciones: list[dict]) -> dict:
    puntos = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
        "properties": {"fecha_hora": p["fecha_hora"].isoformat(), "temperatura": p.get("temperatura"),
                       "sensor_id": p["meta"]["sensor_id"]},
    } for p in posiciones]
    linea = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[p["lon"], p["lat"]] for p in posiciones]},
        "properties": {"contenedor": contenedor["codigo_internacional"], "puntos": len(posiciones)},
    }
    return {"type": "FeatureCollection", "features": ([linea] if len(posiciones) > 1 else []) + puntos}
