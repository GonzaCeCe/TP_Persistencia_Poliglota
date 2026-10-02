import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from app.infra.errores import ErrorNegocio

CENTAVO = Decimal("0.01")
LARGO_MINIMO_PASSWORD = 8
LARGO_MAXIMO_MENSAJE = 2000

ESTADO_POR_EVENTO = {
    "CARGA_INICIADA": "EN_CARGA",
    "EN_TRANSITO": "EN_TRANSITO",
    "ADUANA": "EN_ADUANA",
    "DESCARGA": "EN_DESCARGA",
    "ENTREGADO": "ENTREGADO",
    "RETRASO": None,
}
ESTADOS_CERRADOS = {"ENTREGADO", "CANCELADO"}
VEHICULOS_POR_MEDIO = {
    "TERRESTRE": {"CAMION", "TREN"},
    "MARITIMO": {"BUQUE"},
    "AEREO": {"AVION"},
}
RANGOS_DE_MEDIDAS = {
    "humedad": (0, 100),
    "bateria": (0, 100),
    "lat": (-90, 90),
    "lon": (-180, 180),
}
MEDIDAS = ("temperatura", "humedad", "vibracion", "lat", "lon", "bateria")
PATRON_PERIODO = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
PATRON_UBICACION = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}$")


@dataclass(frozen=True)
class Anomalia:
    tipo: str
    valor: float
    umbral: float


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def crear_ubicacion(codigo: str, ciudad: str, pais: str) -> dict:
    codigo, ciudad, pais = codigo.strip().upper(), ciudad.strip(), pais.strip().upper()
    if not PATRON_UBICACION.match(codigo):
        raise ErrorNegocio(f"Código de ubicación inválido: {codigo!r} (UN/LOCODE, por ejemplo ARBUE)")
    if codigo[:2] != pais:
        raise ErrorNegocio(f"El código {codigo} no corresponde al país {pais}")
    if not ciudad:
        raise ErrorNegocio("Falta la ciudad de la ubicación")
    return {"codigo": codigo, "ciudad": ciudad, "pais": pais}


def validar_carga(peso_kg: float, volumen_m3: float, capacidades_m3: list[Decimal]) -> None:
    if peso_kg <= 0 or volumen_m3 <= 0:
        raise ErrorNegocio("El peso y el volumen deben ser mayores a cero")
    capacidad_total = sum(capacidades_m3, Decimal("0"))
    if Decimal(str(volumen_m3)) > capacidad_total:
        raise ErrorNegocio(f"El volumen ({volumen_m3} m3) supera la capacidad de los contenedores ({capacidad_total} m3)")


def validar_password(password: str) -> None:
    if len(password) < LARGO_MINIMO_PASSWORD:
        raise ErrorNegocio(f"La contraseña debe tener al menos {LARGO_MINIMO_PASSWORD} caracteres")


def importe_con_margen(costos: Iterable[Decimal | float], margen: Decimal) -> Decimal:
    subtotal = sum((Decimal(str(costo)) for costo in costos), Decimal("0"))
    return (subtotal * (1 + margen)).quantize(CENTAVO, ROUND_HALF_UP)


def validar_medidas(medidas: dict) -> None:
    if all(medidas.get(nombre) is None for nombre in MEDIDAS):
        raise ErrorNegocio("La lectura no tiene ninguna medida")
    if (medidas.get("lat") is None) != (medidas.get("lon") is None):
        raise ErrorNegocio("La posición GPS necesita latitud y longitud")
    for nombre, (minimo, maximo) in RANGOS_DE_MEDIDAS.items():
        valor = medidas.get(nombre)
        if valor is not None and not minimo <= valor <= maximo:
            raise ErrorNegocio(f"{nombre} fuera de rango ({minimo} a {maximo}): {valor}")


def evaluar_lectura(temperatura: float | None, bateria: float | None,
                    temp_min: float, temp_max: float, umbral_bateria: float) -> list[Anomalia]:
    anomalias = []
    if temperatura is not None and temperatura > temp_max:
        anomalias.append(Anomalia("TEMP_FUERA_RANGO", temperatura, temp_max))
    elif temperatura is not None and temperatura < temp_min:
        anomalias.append(Anomalia("TEMP_FUERA_RANGO", temperatura, temp_min))
    if bateria is not None and bateria < umbral_bateria:
        anomalias.append(Anomalia("BATERIA_BAJA", bateria, umbral_bateria))
    return anomalias


def id_conversacion_privada(usuario_a: int, usuario_b: int) -> str:
    if usuario_a == usuario_b:
        raise ErrorNegocio("No se puede enviar un mensaje privado a uno mismo")
    menor, mayor = sorted((usuario_a, usuario_b))
    return f"u{menor}-u{mayor}"


def id_conversacion_grupal(grupo_id: int) -> str:
    return f"g{grupo_id}"


def validar_contenido_mensaje(contenido: str) -> str:
    limpio = contenido.strip()
    if not 1 <= len(limpio) <= LARGO_MAXIMO_MENSAJE:
        raise ErrorNegocio(f"El mensaje debe tener entre 1 y {LARGO_MAXIMO_MENSAJE} caracteres")
    return limpio


def validar_periodo(periodo: str) -> str:
    if not PATRON_PERIODO.match(periodo):
        raise ErrorNegocio(f"Período inválido: {periodo!r} (formato AAAA-MM)")
    return periodo


def periodo_de(fecha: date) -> str:
    return f"{fecha.year:04d}-{fecha.month:02d}"


def inicio_periodo(periodo: str) -> date:
    anio, mes = validar_periodo(periodo).split("-")
    return date(int(anio), int(mes), 1)


def inicio_periodo_siguiente(periodo: str) -> date:
    inicio = inicio_periodo(periodo)
    if inicio.month == 12:
        return date(inicio.year + 1, 1, 1)
    return date(inicio.year, inicio.month + 1, 1)


def periodo_anterior(periodo: str) -> str:
    inicio = inicio_periodo(periodo)
    if inicio.month == 1:
        return f"{inicio.year - 1:04d}-12"
    return f"{inicio.year:04d}-{inicio.month - 1:02d}"


def fin_periodo_utc(periodo: str) -> datetime:
    return datetime.combine(inicio_periodo_siguiente(periodo), time.min, tzinfo=timezone.utc)


def fecha_emision(periodo: str) -> date:
    return inicio_periodo_siguiente(periodo)


def periodo_terminado(periodo: str, hoy: date) -> bool:
    return hoy >= inicio_periodo_siguiente(periodo)


def validar_pago(monto: Decimal, fecha: date, estado_factura: str,
                 fecha_emision_factura: date, saldo_pendiente: Decimal) -> None:
    if monto <= 0:
        raise ErrorNegocio("El monto del pago debe ser mayor a cero")
    if estado_factura in ("PAGADA", "ANULADA"):
        raise ErrorNegocio(f"La factura está {estado_factura} y no admite pagos")
    if fecha < fecha_emision_factura:
        raise ErrorNegocio(f"El pago no puede ser anterior a la emisión ({fecha_emision_factura})")
    if monto > saldo_pendiente:
        raise ErrorNegocio(f"El pago ({monto}) supera el saldo pendiente ({saldo_pendiente})")


def estado_factura_tras_pago(importe_total: Decimal, total_pagado: Decimal) -> str:
    return "PAGADA" if total_pagado >= importe_total else "PAGADA_PARCIAL"


def estado_tras_evento(tipo_evento: str) -> str | None:
    if tipo_evento not in ESTADO_POR_EVENTO:
        raise ErrorNegocio(f"Tipo de evento inválido: {tipo_evento}")
    return ESTADO_POR_EVENTO[tipo_evento]


def envio_activo(estado: str) -> bool:
    return estado not in ESTADOS_CERRADOS


def envio_demorado(estado: str, fecha_estimada: datetime | None,
                   fecha_real: datetime | None, ahora: datetime) -> bool:
    if fecha_estimada is None or estado == "CANCELADO":
        return False
    if estado == "ENTREGADO":
        return fecha_real is not None and fecha_real > fecha_estimada
    return fecha_estimada < ahora


def ruta(codigo_origen: str, codigo_destino: str) -> str:
    return f"{codigo_origen}-{codigo_destino}"


def validar_tramo(medio: str, tipo_vehiculo: str, salida: datetime, llegada_estimada: datetime,
                  origen_esperado: str, origen: str) -> None:
    if medio not in VEHICULOS_POR_MEDIO:
        raise ErrorNegocio(f"Medio de transporte inválido: {medio}")
    if tipo_vehiculo not in VEHICULOS_POR_MEDIO[medio]:
        raise ErrorNegocio(f"Un vehículo {tipo_vehiculo} no es compatible con el medio {medio}")
    if llegada_estimada <= salida:
        raise ErrorNegocio("La llegada estimada debe ser posterior a la salida")
    if origen != origen_esperado:
        raise ErrorNegocio(f"El tramo debe salir de {origen_esperado}, donde termina el recorrido anterior")


def origen_esperado_del_tramo(origen_envio: str, tramos: list[dict]) -> str:
    if not tramos:
        return origen_envio
    return max(tramos, key=lambda tramo: tramo["orden"])["destino"]["codigo"]


def fecha_entrega_estimada(tramos: list[dict]) -> datetime | None:
    if not tramos:
        return None
    return max(tramo["fecha_llegada_estimada"] for tramo in tramos)


def tramo_vigente(tramos: list[dict], momento: datetime) -> dict | None:
    iniciados = [tramo for tramo in tramos if tramo["fecha_salida"] <= momento]
    if not iniciados:
        return None
    return max(iniciados, key=lambda tramo: tramo["orden"])


def tasa_demora(entregados: int, demorados: int) -> float:
    return 0.0 if entregados == 0 else demorados / entregados


def riesgo_operativo(incidentes_abiertos: int, alertas_abiertas: int) -> float:
    return round(min(1.0, 0.25 * incidentes_abiertos + 0.1 * alertas_abiertas), 4)


def probabilidad_demora(tasa_demora_ruta: float, riesgo_operativo_envio: float,
                        riesgo_climatico: float, vencido: bool) -> float:
    if vencido:
        return 1.0
    valor = 0.5 * tasa_demora_ruta + 0.3 * riesgo_operativo_envio + 0.2 * riesgo_climatico
    return round(min(1.0, valor), 4)
