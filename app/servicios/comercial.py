import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal

from app.dominio import reglas
from app.infra.errores import ErrorNegocio
from app.repositorios.documental import RepositorioDocumental
from app.repositorios.relacional import RepositorioRelacional
from app.servicios.auth import NIVEL_ADMIN, NIVEL_OPERADOR, SesionActiva, requerir_nivel

log = logging.getLogger(__name__)

MEDIOS_DE_PAGO = ("TRANSFERENCIA", "TARJETA", "CHEQUE", "EFECTIVO")


def _decimal(valor: float) -> Decimal:
    return Decimal(str(valor)).quantize(reglas.CENTAVO)


class ServicioComercial:
    def __init__(self, relacional: RepositorioRelacional, documental: RepositorioDocumental, margen: Decimal):
        self._rel = relacional
        self._doc = documental
        self._margen = margen

    def _validar_periodo_terminado(self, periodo: str, hoy: date | None) -> None:
        reglas.validar_periodo(periodo)
        if not reglas.periodo_terminado(periodo, hoy or reglas.ahora_utc().date()):
            raise ErrorNegocio(f"El período {periodo} todavía no terminó")

    def _validar_periodo_abierto(self, fecha: date) -> None:
        if self._rel.existe_cierre(reglas.periodo_de(fecha)):
            raise ErrorNegocio(f"El período {reglas.periodo_de(fecha)} ya tiene cierre mensual")

    # Facturación

    def facturar_periodo(self, sesion: SesionActiva, periodo: str, hoy: date | None = None) -> dict:
        requerir_nivel(sesion, NIVEL_ADMIN)
        self._validar_periodo_terminado(periodo, hoy)
        emision = reglas.fecha_emision(periodo)
        self._validar_periodo_abierto(emision)
        candidatos = self._doc.envios_para_facturar(reglas.fin_periodo_utc(periodo))
        reconciliados = self._reconciliar(candidatos)
        pendientes = [envio for envio in candidatos if envio["_id"] not in reconciliados]
        sin_costo = [envio["_id"] for envio in pendientes if self._importe(envio) == 0]
        if sin_costo:
            log.warning("Envíos entregados sin costo de tramos, no se facturan: %s", sin_costo)
        por_cliente = defaultdict(list)
        for envio in pendientes:
            if envio["_id"] not in sin_costo:
                por_cliente[envio["cliente"]["id"]].append(envio)
        facturas = [self._facturar_cliente(cliente_id, periodo, emision, envios)
                    for cliente_id, envios in sorted(por_cliente.items())]
        log.info("Facturación %s: %s facturas, %s envíos reconciliados", periodo, len(facturas), len(reconciliados))
        return {"periodo": periodo, "facturas": facturas, "reconciliados": sorted(reconciliados), "sin_costo": sin_costo}

    def _importe(self, envio: dict) -> Decimal:
        return reglas.importe_con_margen([tramo["costo"] for tramo in envio["tramos"]], self._margen)

    def _reconciliar(self, candidatos: list[dict]) -> set[int]:
        ya_facturados = self._rel.facturas_de_envios([envio["_id"] for envio in candidatos])
        envios_por_factura = defaultdict(list)
        for envio_id, factura_id in ya_facturados.items():
            envios_por_factura[factura_id].append(envio_id)
        for factura_id, envio_ids in envios_por_factura.items():
            self._doc.marcar_facturados(envio_ids, factura_id)
        if ya_facturados:
            log.warning("Reconciliación: envíos %s ya tenían ítem de factura; se marcaron en MongoDB",
                        sorted(ya_facturados))
        return set(ya_facturados)

    def _facturar_cliente(self, cliente_id: int, periodo: str, emision: date, envios: list[dict]) -> dict:
        importes = {envio["_id"]: self._importe(envio) for envio in envios}
        total = sum(importes.values(), Decimal("0"))
        costos_operador = defaultdict(Decimal)
        for envio in envios:
            for tramo in envio["tramos"]:
                costos_operador[(tramo["operador"]["id"], envio["_id"])] += _decimal(tramo["costo"])
        with self._rel.transaccion():
            cuenta_cliente = self._rel.obtener_cuenta(cliente_id=cliente_id)["id"]
            cuentas_operador = {operador_id: self._rel.obtener_cuenta(empresa_id=operador_id)["id"]
                                for operador_id, _ in costos_operador}
            self._rel.bloquear_cuentas([cuenta_cliente, *cuentas_operador.values()])
            factura_id = self._rel.insertar_factura(cliente_id, periodo, emision, total)
            for envio_id, importe in importes.items():
                self._rel.insertar_item(factura_id, envio_id, importe)
            self._rel.registrar_movimiento(cuenta_cliente, emision, "DEBE", total,
                                           f"Factura {factura_id} período {periodo}", factura_id=factura_id)
            for (operador_id, envio_id), costo in costos_operador.items():
                if costo > 0:
                    self._rel.registrar_movimiento(cuentas_operador[operador_id], emision, "HABER", costo,
                                                   f"Transporte envío {envio_id} (factura {factura_id})",
                                                   factura_id=factura_id, envio_id=envio_id)
        self._doc.marcar_facturados(list(importes), factura_id)
        log.info("Factura %s emitida al cliente %s por %s (envíos %s)", factura_id, cliente_id, total, sorted(importes))
        return {"factura_id": factura_id, "cliente_id": cliente_id, "importe_total": total, "envios": sorted(importes)}

    # Pagos y cuentas corrientes

    def registrar_pago(self, sesion: SesionActiva, factura_id: int, monto: Decimal, medio_pago: str,
                       fecha: date | None = None) -> dict:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        if medio_pago not in MEDIOS_DE_PAGO:
            raise ErrorNegocio(f"Medio de pago inválido: {medio_pago}")
        fecha = fecha or reglas.ahora_utc().date()
        self._validar_periodo_abierto(fecha)
        with self._rel.transaccion():
            factura = self._rel.bloquear_factura(factura_id)
            pendiente = factura["importe_total"] - factura["pagado"]
            reglas.validar_pago(monto, fecha, factura["estado"], factura["fecha_emision"], pendiente)
            pago_id = self._rel.insertar_pago(factura_id, fecha, monto, medio_pago)
            estado = reglas.estado_factura_tras_pago(factura["importe_total"], factura["pagado"] + monto)
            self._rel.actualizar_estado_factura(factura_id, estado)
            cuenta = self._rel.obtener_cuenta(cliente_id=factura["cliente_id"])
            self._rel.registrar_movimiento(cuenta["id"], fecha, "HABER", monto,
                                           f"Pago {pago_id} de la factura {factura_id} ({medio_pago})",
                                           factura_id=factura_id, pago_id=pago_id)
        log.info("Pago %s de %s sobre la factura %s: queda %s", pago_id, monto, factura_id, estado)
        return {"pago_id": pago_id, "estado_factura": estado, "saldo_pendiente": pendiente - monto}

    def listar_cuentas(self, sesion: SesionActiva) -> list[dict]:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        return self._rel.listar_cuentas()

    def estado_de_cuenta(self, sesion: SesionActiva, cliente_id: int | None = None,
                         empresa_id: int | None = None) -> dict:
        if sesion.cliente_id is not None:
            cliente_id, empresa_id = sesion.cliente_id, None
        else:
            requerir_nivel(sesion, NIVEL_OPERADOR)
        cuenta = self._rel.obtener_cuenta(cliente_id=cliente_id, empresa_id=empresa_id)
        facturas = self._rel.facturas_de_cliente(cliente_id) if cliente_id is not None else []
        return {"cuenta": cuenta,
                "movimientos": self._rel.movimientos_de_cuenta(cuenta["id"]),
                "cierres": self._rel.cierres_de_cuenta(cuenta["id"]),
                "facturas": [{**f, "pendiente": f["importe_total"] - f["pagado"]} for f in facturas]}

    def cierre_mensual(self, sesion: SesionActiva, periodo: str, hoy: date | None = None) -> int:
        requerir_nivel(sesion, NIVEL_ADMIN)
        self._validar_periodo_terminado(periodo, hoy)
        cerradas = self._rel.cerrar_periodo(periodo, reglas.periodo_anterior(periodo), reglas.inicio_periodo(periodo),
                                            reglas.inicio_periodo_siguiente(periodo))
        log.info("Cierre mensual %s: %s cuentas cerradas", periodo, cerradas)
        return cerradas

    # Control de integridad

    def control_integridad(self, sesion: SesionActiva) -> dict:
        requerir_nivel(sesion, NIVEL_ADMIN)
        marcados = self._doc.envios_marcados_como_facturados()
        con_item = self._rel.facturas_de_envios([envio["_id"] for envio in marcados])
        resultado = {
            "cuentas_con_saldo_distinto_a_movimientos": self._rel.cuentas_con_saldo_inconsistente(),
            "facturas_con_importe_distinto_a_items": self._rel.facturas_con_importe_inconsistente(),
            "envios_facturados_sin_item": [{"envio_id": envio["_id"], "factura_id": envio.get("factura_id")}
                                           for envio in marcados if envio["_id"] not in con_item],
        }
        problemas = sum(len(filas) for filas in resultado.values())
        if problemas:
            log.warning("Control de integridad: %s inconsistencias encontradas", problemas)
        else:
            log.info("Control de integridad sin inconsistencias")
        return resultado
