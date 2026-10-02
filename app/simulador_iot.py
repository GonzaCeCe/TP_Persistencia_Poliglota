import argparse
import random
import time
from dataclasses import dataclass

from app.ensamblado import crear_aplicacion
from app.infra.errores import ErrorAplicacion


@dataclass
class EstadoSimulado:
    lat: float
    lon: float
    bateria: float


def leer_argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulador de sensores IoT: envía lecturas periódicas.")
    parser.add_argument("--sensores", required=True, help="ids de sensores separados por coma, por ejemplo 1,2")
    parser.add_argument("--intervalo", type=float, default=5.0, help="segundos entre rondas (por defecto 5)")
    parser.add_argument("--rondas", type=int, default=0, help="cantidad de rondas; 0 = hasta Ctrl+C")
    parser.add_argument("--temperatura", type=float, default=5.0, help="temperatura base en °C (por defecto 5)")
    parser.add_argument("--prob-anomalia", type=float, default=0.1, help="probabilidad de un pico de temperatura")
    parser.add_argument("--lat", type=float, default=-34.60, help="latitud inicial (por defecto puerto de Buenos Aires)")
    parser.add_argument("--lon", type=float, default=-58.37, help="longitud inicial")
    parser.add_argument("--semilla", type=int, help="semilla aleatoria para repetir una simulación")
    return parser.parse_args()


def generar_lectura(estado: EstadoSimulado, argumentos: argparse.Namespace, azar: random.Random) -> dict:
    estado.lat = min(90.0, estado.lat + azar.uniform(0.0, 0.05))
    estado.lon = min(180.0, estado.lon + azar.uniform(0.0, 0.08))
    estado.bateria = max(0.0, estado.bateria - azar.uniform(0.1, 0.5))
    pico = azar.uniform(4.0, 7.0) if azar.random() < argumentos.prob_anomalia else 0.0
    return {
        "temperatura": round(argumentos.temperatura + azar.gauss(0, 0.8) + pico, 2),
        "humedad": round(min(100.0, max(0.0, azar.gauss(70, 5))), 1),
        "vibracion": round(abs(azar.gauss(0.2, 0.1)), 3),
        "lat": round(estado.lat, 5),
        "lon": round(estado.lon, 5),
        "bateria": round(estado.bateria, 1),
    }


def main() -> None:
    argumentos = leer_argumentos()
    sensor_ids = [int(x) for x in argumentos.sensores.split(",") if x.strip()]
    azar = random.Random(argumentos.semilla)
    estados = {sensor_id: EstadoSimulado(argumentos.lat, argumentos.lon, 100.0) for sensor_id in sensor_ids}
    app = crear_aplicacion()
    print(f"Simulando sensores {sensor_ids} cada {argumentos.intervalo} s. Ctrl+C para terminar.")
    ronda = 0
    try:
        while argumentos.rondas == 0 or ronda < argumentos.rondas:
            ronda += 1
            for sensor_id, estado in estados.items():
                medidas = generar_lectura(estado, argumentos, azar)
                try:
                    alertas = app.monitoreo.registrar_lectura(sensor_id, medidas)
                except ErrorAplicacion as error:
                    print(f"  sensor {sensor_id}: rechazada ({error})")
                    continue
                print(f"  ronda {ronda} sensor {sensor_id}: {medidas}")
                for alerta in alertas:
                    print(f"    ALERTA {alerta['tipo']} valor {alerta['valor']} umbral {alerta['umbral']}")
            if argumentos.rondas == 0 or ronda < argumentos.rondas:
                time.sleep(argumentos.intervalo)
    except KeyboardInterrupt:
        print("\nSimulación detenida.")
    finally:
        app.cerrar()


if __name__ == "__main__":
    main()
