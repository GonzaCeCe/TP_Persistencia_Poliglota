from datetime import date
from unittest.mock import MagicMock

from app.procesos_automaticos import ejecutar_proceso
from app.servicios.prediccion import ClimaHistorico


class DocumentalFalso:
    def todos_los_envios(self):
        return [
            {
                "_id": 1,
                "estado": "ENTREGADO",
                "origen": {"codigo": "AR"},
                "destino": {"codigo": "BR"},
            },
            {
                "_id": 2,
                "estado": "ENTREGADO",
                "origen": {"codigo": "AR"},
                "destino": {"codigo": "BR"},
            },
        ]

    def incidentes_de_envio(self, envio_id):
        if envio_id == 1:
            return [{"tipo": "CLIMA"}]
        return []


def test_riesgo_climatico_historico():
    clima = ClimaHistorico(DocumentalFalso())
    clima.actualizar()

    envio = {
        "origen": {"codigo": "AR"},
        "destino": {"codigo": "BR"},
    }

    assert clima.riesgo_climatico(envio) == 0.5


def test_ruta_sin_antecedentes_climaticos():
    clima = ClimaHistorico(DocumentalFalso())
    clima.actualizar()

    envio = {
        "origen": {"codigo": "AR"},
        "destino": {"codigo": "CL"},
    }

    assert clima.riesgo_climatico(envio) == 0.0


def test_proceso_diario_registra_ejecucion():
    app = MagicMock()
    redis = app.conexiones.redis.return_value
    redis.exists.return_value = False
    redis.set.return_value = True
    app.monitoreo.detectar_sensores_inactivos.return_value = []
    app.prediccion.predecir_riesgos.return_value = [{}]

    ejecutar_proceso(app, "diario", date(2026, 11, 6))

    app.monitoreo.detectar_sensores_inactivos.assert_called_once()
    app.prediccion.predecir_riesgos.assert_called_once()
    assert redis.set.call_count == 2


def test_proceso_completado_no_se_repite():
    app = MagicMock()
    redis = app.conexiones.redis.return_value
    redis.exists.return_value = True

    ejecutar_proceso(app, "diario", date(2026, 11, 6))

    app.monitoreo.detectar_sensores_inactivos.assert_not_called()
    app.prediccion.predecir_riesgos.assert_not_called()