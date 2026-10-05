import logging
from datetime import date
from typing import Protocol

from app.dominio import reglas
from app.repositorios.documental import RepositorioDocumental
from app.servicios.auth import NIVEL_ADMIN, NIVEL_OPERADOR, SesionActiva, requerir_nivel, verificar_acceso_a_envio

log = logging.getLogger(__name__)


class ProveedorClima(Protocol):
    def riesgo_climatico(self, envio: dict) -> float:
        ...


class ClimaSinFuenteDeDatos:
    def riesgo_climatico(self, envio: dict) -> float:
        return 0.0


class ServicioPrediccion:
    def __init__(self, documental: RepositorioDocumental, proveedor_clima: ProveedorClima):
        self._doc = documental
        self._clima = proveedor_clima

    def predecir_riesgos(self, sesion: SesionActiva, dia: date | None = None) -> list[dict]:
        requerir_nivel(sesion, NIVEL_ADMIN)
        momento = reglas.ahora_utc()
        dia_texto = (dia or momento.date()).isoformat()
        demoras_por_ruta = self._doc.demoras_por_ruta()
        incidentes_abiertos = self._doc.incidentes_abiertos_por_envio()
        alertas_abiertas = self._doc.alertas_abiertas_por_contenedor()
        predicciones = []
        for envio in self._doc.envios_activos():
            ruta = reglas.ruta(envio["origen"]["codigo"], envio["destino"]["codigo"])
            entregados, tasa = demoras_por_ruta.get(ruta, (0, 0.0))
            incidentes = incidentes_abiertos.get(envio["_id"], 0)
            alertas = sum(alertas_abiertas.get(c["id"], 0) for c in envio["contenedores"])
            operativo = reglas.riesgo_operativo(incidentes, alertas)
            climatico = self._clima.riesgo_climatico(envio)
            vencido = envio["fecha_entrega_estimada"] is not None and envio["fecha_entrega_estimada"] < momento
            prediccion = {
                "envio_id": envio["_id"],
                "dia": dia_texto,
                "probabilidad_demora": reglas.probabilidad_demora(tasa, operativo, climatico, vencido),
                "riesgo_climatico": climatico,
                "riesgo_operativo": operativo,
                "fecha_calculo": momento,
                "factores": {"ruta": ruta, "envios_entregados_en_ruta": entregados,
                             "tasa_demora_ruta": round(tasa, 4), "incidentes_abiertos": incidentes,
                             "alertas_abiertas": alertas, "vencido": vencido},
            }
            self._doc.guardar_prediccion(prediccion)
            predicciones.append(prediccion)
        log.info("Predicción diaria %s: %s envíos activos evaluados", dia_texto, len(predicciones))
        return predicciones

    def predicciones_de_envio(self, sesion: SesionActiva, envio_id: int) -> list[dict]:
        verificar_acceso_a_envio(sesion, self._doc.obtener_envio(envio_id))
        return self._doc.predicciones_de_envio(envio_id)

    def predicciones_del_dia(self, sesion: SesionActiva, dia: date | None = None) -> list[dict]:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        return self._doc.predicciones_del_dia((dia or reglas.ahora_utc().date()).isoformat())
