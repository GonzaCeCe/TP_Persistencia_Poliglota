from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.dominio import reglas
from app.infra.errores import ErrorNegocio

MARGEN = Decimal("0.25")


def utc(anio, mes, dia, hora=0):
    return datetime(anio, mes, dia, hora, tzinfo=timezone.utc)


def tramo(orden, salida, llegada, destino="BRSSZ"):
    return {"orden": orden, "fecha_salida": salida, "fecha_llegada_estimada": llegada,
            "destino": {"codigo": destino}}


class TestImporteConMargen:
    def test_suma_costos_y_aplica_margen(self):
        assert reglas.importe_con_margen([Decimal("1000"), Decimal("600")], MARGEN) == Decimal("2000.00")

    def test_redondea_a_centavos(self):
        assert reglas.importe_con_margen([Decimal("0.05")], MARGEN) == Decimal("0.06")

    def test_acepta_costos_float_sin_error_de_representacion(self):
        assert reglas.importe_con_margen([0.1, 0.2], MARGEN) == Decimal("0.38")

    def test_sin_tramos_es_cero(self):
        assert reglas.importe_con_margen([], MARGEN) == Decimal("0.00")


class TestEvaluarLectura:
    def test_temperatura_dentro_de_rango_no_genera_anomalias(self):
        assert reglas.evaluar_lectura(5.0, 80, 2, 8, 15) == []

    def test_temperatura_sobre_el_maximo(self):
        assert reglas.evaluar_lectura(9.8, 80, 2, 8, 15) == [reglas.Anomalia("TEMP_FUERA_RANGO", 9.8, 8)]

    def test_temperatura_bajo_el_minimo(self):
        assert reglas.evaluar_lectura(1.5, 80, 2, 8, 15) == [reglas.Anomalia("TEMP_FUERA_RANGO", 1.5, 2)]

    def test_los_limites_son_validos(self):
        assert reglas.evaluar_lectura(8, 15, 2, 8, 15) == []

    def test_bateria_baja(self):
        assert reglas.evaluar_lectura(None, 10, 2, 8, 15) == [reglas.Anomalia("BATERIA_BAJA", 10, 15)]

    def test_dos_anomalias_a_la_vez(self):
        tipos = [a.tipo for a in reglas.evaluar_lectura(12, 5, 2, 8, 15)]
        assert tipos == ["TEMP_FUERA_RANGO", "BATERIA_BAJA"]


class TestValidarMedidas:
    def test_lectura_vacia_es_invalida(self):
        with pytest.raises(ErrorNegocio):
            reglas.validar_medidas({})

    def test_gps_incompleto_es_invalido(self):
        with pytest.raises(ErrorNegocio):
            reglas.validar_medidas({"lat": -34.6})

    @pytest.mark.parametrize("medida,valor", [("humedad", 101), ("bateria", -1), ("lat", 91), ("lon", -181)])
    def test_valores_fuera_de_rango(self, medida, valor):
        medidas = {"lat": 0, "lon": 0}
        medidas[medida] = valor
        with pytest.raises(ErrorNegocio):
            reglas.validar_medidas(medidas)

    def test_lectura_valida(self):
        reglas.validar_medidas({"temperatura": 4.5, "lat": -34.6, "lon": -58.4, "bateria": 90})


class TestConversaciones:
    def test_id_privado_es_simetrico(self):
        assert reglas.id_conversacion_privada(7, 3) == reglas.id_conversacion_privada(3, 7) == "u3-u7"

    def test_no_se_puede_escribir_a_uno_mismo(self):
        with pytest.raises(ErrorNegocio):
            reglas.id_conversacion_privada(4, 4)

    def test_id_grupal(self):
        assert reglas.id_conversacion_grupal(2) == "g2"

    @pytest.mark.parametrize("contenido", ["", "   ", "x" * 2001])
    def test_contenido_invalido(self, contenido):
        with pytest.raises(ErrorNegocio):
            reglas.validar_contenido_mensaje(contenido)


class TestPeriodos:
    @pytest.mark.parametrize("periodo", ["2026-13", "2026-1", "26-01", "2026/01"])
    def test_periodo_invalido(self, periodo):
        with pytest.raises(ErrorNegocio):
            reglas.validar_periodo(periodo)

    def test_emision_es_el_primer_dia_del_mes_siguiente(self):
        assert reglas.fecha_emision("2026-03") == date(2026, 4, 1)

    def test_emision_de_diciembre_pasa_de_anio(self):
        assert reglas.fecha_emision("2026-12") == date(2027, 1, 1)

    def test_periodo_anterior_de_enero(self):
        assert reglas.periodo_anterior("2026-01") == "2025-12"

    def test_fin_de_periodo_en_utc(self):
        assert reglas.fin_periodo_utc("2026-02") == utc(2026, 3, 1)

    def test_periodo_terminado(self):
        assert reglas.periodo_terminado("2026-08", date(2026, 9, 1))
        assert not reglas.periodo_terminado("2026-09", date(2026, 9, 30))

    def test_periodo_de_una_fecha(self):
        assert reglas.periodo_de(date(2026, 7, 31)) == "2026-07"


class TestPagos:
    def validar(self, monto="100", fecha=date(2026, 4, 2), estado="EMITIDA", pendiente="100"):
        reglas.validar_pago(Decimal(monto), fecha, estado, date(2026, 4, 1), Decimal(pendiente))

    def test_pago_valido(self):
        self.validar()

    def test_pago_que_excede_el_saldo(self):
        with pytest.raises(ErrorNegocio, match="supera"):
            self.validar(monto="100.01")

    def test_pago_anterior_a_la_emision(self):
        with pytest.raises(ErrorNegocio, match="anterior"):
            self.validar(fecha=date(2026, 3, 31))

    def test_factura_pagada_no_admite_pagos(self):
        with pytest.raises(ErrorNegocio):
            self.validar(estado="PAGADA")

    def test_estado_tras_pago(self):
        assert reglas.estado_factura_tras_pago(Decimal("100"), Decimal("40")) == "PAGADA_PARCIAL"
        assert reglas.estado_factura_tras_pago(Decimal("100"), Decimal("100")) == "PAGADA"


class TestEnvios:
    def test_estado_segun_evento(self):
        assert reglas.estado_tras_evento("ADUANA") == "EN_ADUANA"
        assert reglas.estado_tras_evento("RETRASO") is None

    def test_evento_desconocido(self):
        with pytest.raises(ErrorNegocio):
            reglas.estado_tras_evento("PERDIDO")

    def test_demorado_en_curso_y_vencido(self):
        assert reglas.envio_demorado("EN_TRANSITO", utc(2026, 9, 1), None, utc(2026, 9, 2))

    def test_no_demorado_en_curso_y_en_fecha(self):
        assert not reglas.envio_demorado("EN_TRANSITO", utc(2026, 9, 3), None, utc(2026, 9, 2))

    def test_entregado_tarde(self):
        assert reglas.envio_demorado("ENTREGADO", utc(2026, 5, 1), utc(2026, 5, 3), utc(2026, 9, 2))

    def test_entregado_a_tiempo(self):
        assert not reglas.envio_demorado("ENTREGADO", utc(2026, 5, 1), utc(2026, 4, 30), utc(2026, 9, 2))


class TestTramos:
    def validar(self, medio="MARITIMO", vehiculo="BUQUE", salida=utc(2026, 5, 1),
                llegada=utc(2026, 5, 10), origen="ARBUE"):
        reglas.validar_tramo(medio, vehiculo, salida, llegada, "ARBUE", origen)

    def test_tramo_valido(self):
        self.validar()

    def test_tren_es_terrestre(self):
        self.validar(medio="TERRESTRE", vehiculo="TREN")

    def test_medio_incompatible_con_vehiculo(self):
        with pytest.raises(ErrorNegocio, match="compatible"):
            self.validar(vehiculo="CAMION")

    def test_llegada_no_posterior_a_salida(self):
        with pytest.raises(ErrorNegocio, match="posterior"):
            self.validar(llegada=utc(2026, 5, 1))

    def test_origen_discontinuo(self):
        with pytest.raises(ErrorNegocio, match="salir"):
            self.validar(origen="UYMVD")

    def test_origen_esperado_es_el_destino_del_ultimo_tramo(self):
        tramos = [tramo(2, utc(2026, 5, 2), utc(2026, 5, 9), "BRSSZ"), tramo(1, utc(2026, 5, 1), utc(2026, 5, 2), "UYMVD")]
        assert reglas.origen_esperado_del_tramo("ARBUE", tramos) == "BRSSZ"
        assert reglas.origen_esperado_del_tramo("ARBUE", []) == "ARBUE"

    def test_entrega_estimada_es_la_ultima_llegada(self):
        tramos = [tramo(1, utc(2026, 5, 1), utc(2026, 5, 3)), tramo(2, utc(2026, 5, 3), utc(2026, 5, 9))]
        assert reglas.fecha_entrega_estimada(tramos) == utc(2026, 5, 9)
        assert reglas.fecha_entrega_estimada([]) is None

    def test_tramo_vigente(self):
        tramos = [tramo(1, utc(2026, 5, 1), utc(2026, 5, 3)), tramo(2, utc(2026, 5, 3), utc(2026, 5, 9))]
        assert reglas.tramo_vigente(tramos, utc(2026, 5, 5))["orden"] == 2
        assert reglas.tramo_vigente(tramos, utc(2026, 5, 2))["orden"] == 1
        assert reglas.tramo_vigente(tramos, utc(2026, 4, 30)) is None


class TestPrediccion:
    def test_riesgo_operativo(self):
        assert reglas.riesgo_operativo(1, 2) == 0.45

    def test_riesgo_operativo_tope_uno(self):
        assert reglas.riesgo_operativo(4, 3) == 1.0

    def test_probabilidad_ponderada(self):
        assert reglas.probabilidad_demora(0.5, 0.45, 0.0, vencido=False) == 0.385

    def test_probabilidad_tope_uno(self):
        assert reglas.probabilidad_demora(1, 1, 1, vencido=False) == 1.0

    def test_envio_vencido_tiene_probabilidad_uno(self):
        assert reglas.probabilidad_demora(0, 0, 0, vencido=True) == 1.0

    def test_tasa_de_demora(self):
        assert reglas.tasa_demora(2, 1) == 0.5
        assert reglas.tasa_demora(0, 0) == 0.0


def test_password_corta():
    with pytest.raises(ErrorNegocio):
        reglas.validar_password("1234567")
