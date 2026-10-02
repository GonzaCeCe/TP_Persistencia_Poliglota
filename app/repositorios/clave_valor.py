import json
from typing import Iterator

import redis

from app.infra.conexiones import Conexiones

CANAL_ALERTAS = "alertas"
CLAVE_POSICIONES = "contenedores:geo"
ESPERA_DE_MENSAJE_SEGUNDOS = 1.0


def _clave_sesion(sesion_id: str) -> str:
    return f"sesion:{sesion_id}"


def _clave_sesiones_de_usuario(usuario_id: int) -> str:
    return f"usuario:{usuario_id}:sesiones"


def _clave_heartbeat(sensor_id: int) -> str:
    return f"sensor:{sensor_id}:hb"


def _clave_ultima_lectura(sensor_id: int) -> str:
    return f"sensor:{sensor_id}:ultima"


class RepositorioClaveValor:
    def __init__(self, conexiones: Conexiones):
        self._conexiones = conexiones

    @property
    def _redis(self) -> redis.Redis:
        return self._conexiones.redis()

    def crear_sesion(self, sesion_id: str, usuario_id: int, datos: dict[str, str], ttl_segundos: int) -> None:
        with self._redis.pipeline(transaction=True) as operaciones:
            operaciones.hset(_clave_sesion(sesion_id), mapping=datos)
            operaciones.expire(_clave_sesion(sesion_id), ttl_segundos)
            operaciones.sadd(_clave_sesiones_de_usuario(usuario_id), sesion_id)
            operaciones.execute()

    def obtener_sesion(self, sesion_id: str) -> dict[str, str] | None:
        return self._redis.hgetall(_clave_sesion(sesion_id)) or None

    def renovar_sesion(self, sesion_id: str, ttl_segundos: int) -> bool:
        return bool(self._redis.expire(_clave_sesion(sesion_id), ttl_segundos))

    def existe_sesion(self, sesion_id: str) -> bool:
        return self._redis.exists(_clave_sesion(sesion_id)) == 1

    def sesiones_de_usuario(self, usuario_id: int) -> set[str]:
        return self._redis.smembers(_clave_sesiones_de_usuario(usuario_id))

    def borrar_sesiones(self, usuario_id: int, sesion_ids: list[str]) -> None:
        if not sesion_ids:
            return
        with self._redis.pipeline(transaction=True) as operaciones:
            operaciones.delete(*[_clave_sesion(sesion_id) for sesion_id in sesion_ids])
            operaciones.srem(_clave_sesiones_de_usuario(usuario_id), *sesion_ids)
            operaciones.execute()

    def registrar_heartbeat(self, sensor_id: int, momento: str, ttl_segundos: int) -> None:
        self._redis.set(_clave_heartbeat(sensor_id), momento, ex=ttl_segundos)

    def tiene_heartbeat(self, sensor_id: int) -> bool:
        return self._redis.exists(_clave_heartbeat(sensor_id)) == 1

    def guardar_ultima_lectura(self, sensor_id: int, lectura: dict[str, str]) -> bool:
        clave = _clave_ultima_lectura(sensor_id)
        fecha_guardada = self._redis.hget(clave, "fecha_hora")
        if fecha_guardada is not None and fecha_guardada >= lectura["fecha_hora"]:
            return False
        self._redis.hset(clave, mapping=lectura)
        return True

    def ultima_lectura(self, sensor_id: int) -> dict[str, str]:
        return self._redis.hgetall(_clave_ultima_lectura(sensor_id))

    def actualizar_posicion(self, contenedor_id: int, lon: float, lat: float) -> None:
        self._redis.geoadd(CLAVE_POSICIONES, [lon, lat, str(contenedor_id)])

    def contenedores_en_radio(self, lon: float, lat: float, radio_km: float) -> list[tuple[int, float]]:
        encontrados = self._redis.geosearch(CLAVE_POSICIONES, longitude=lon, latitude=lat, radius=radio_km,
                                            unit="km", withdist=True, sort="ASC")
        return [(int(miembro), distancia) for miembro, distancia in encontrados]

    def publicar_alerta(self, alerta: dict) -> int:
        return self._redis.publish(CANAL_ALERTAS, json.dumps(alerta, default=str, ensure_ascii=False))

    def escuchar_alertas(self) -> Iterator[dict]:
        suscripcion = self._redis.pubsub(ignore_subscribe_messages=True)
        suscripcion.subscribe(CANAL_ALERTAS)
        try:
            while True:
                mensaje = suscripcion.get_message(timeout=ESPERA_DE_MENSAJE_SEGUNDOS)
                if mensaje is not None:
                    yield json.loads(mensaje["data"])
        finally:
            suscripcion.close()
