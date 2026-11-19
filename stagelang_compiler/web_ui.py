"""
Servidor Web Funcional para la Consola de Iluminación, Mezcla y Temporización Escénica
STAGELANG DMX-8 (`web_ui.py`).

Implementado exclusivamente con la biblioteca estándar de Python 3.10+
(`http.server`, `json`, `urllib.parse`, `pathlib`, `webbrowser`).

Rutas HTTP:
- `GET  /`                : Sirve la consola escénica interactiva `ui/index.html`.
- `GET  /api/presets`     : Retorna las rutinas listas para probar en la mesa de luces:
                            `show_apertura`, `show_concierto`, `rutina_con_error_sintaxis`,
                            `rutina_con_error_logico` (además de mantener `/api/ejemplos` como alias).
- `POST /api/ejecutar-show`: Recibe `{"codigo": "..."}`, ejecuta por debajo el pipeline completo
                            de `StageLang` (`FrontEnd` -> `MiddleEnd` -> `BackEnd`) para validar
                            reglas y calcular los valores reales en la máquina virtual IR.
                            - Si hay error: `{"ok": false, "alerta": "Error en línea X: ...", "tipo_fallo": "...", "linea": X}`.
                            - Si compila bien: `{"ok": true, "eventos": [...], "estado_final": {...}}`.
"""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import urllib.parse
import webbrowser

from src.frontend import (
    ErrorLexico,
    ErrorSemantico,
    ErrorSintactico,
)
from src.middle_end import (
    Cuadrupla,
    ErrorEjecucionIR,
)
from src.backend import (
    ErrorMemoria,
)
from src.pipeline import BackEnd, FrontEnd, MiddleEnd


BASE_DIR = Path(__file__).resolve().parent
RUTA_INDEX_HTML = BASE_DIR / "ui" / "index.html"


# =====================================================================
# Rutinas Preprogramadas (Presets) para la Mesa DMX-8
# =====================================================================

PRESETS_DMX: List[Dict[str, Any]] = [
    {
        "id": "show_apertura",
        "titulo": "1. Show Apertura — Obertura Teatral Multi-Escena",
        "categoria": "SHOW",
        "descripcion": "Rutina completa con múltiples escenas, encendido progresivo de canales 1 al 8, mezclas armónicas de intensidad y tiempos de espera.",
        "codigo": (
            "/* =========================================================\n"
            "   RUTINA 1: OBERTURA TEATRAL Y APERTURA DE TELÓN (DMX-8)\n"
            "   ========================================================= */\n\n"
            "// Parámetros maestros del show\n"
            "int base_ambar = 85;\n"
            "int refuerzo_cian = 70;\n"
            "float pausa_corta = 1.5;\n"
            "float pausa_media = 2.0;\n\n"
            "escena apertura {\n"
            "    int spot_frontal = base_ambar + 15;\n"
            "    int wash_lateral = (refuerzo_cian + 10) * 1;\n\n"
            "    canal 1, spot_frontal;\n"
            "    canal 2, wash_lateral;\n"
            "    canal 3, 60;\n"
            "    mezcla 1, 2;\n"
            "    espera pausa_corta;\n\n"
            "    canal 4, 90;\n"
            "    canal 5, 75;\n"
            "    mezcla 4, 5;\n"
            "    espera pausa_media;\n"
            "}\n\n"
            "escena gran_final {\n"
            "    int potencia_climax = (40 + 55);\n"
            "    canal 6, potencia_climax;\n"
            "    canal 7, 100;\n"
            "    canal 8, 95;\n"
            "    mezcla 6, 7, 98;\n"
            "    mezcla 1, 8, 92;\n"
            "    espera 2.5;\n"
            "}\n"
        ),
    },
    {
        "id": "show_concierto",
        "titulo": "2. Show Concierto — Secuencia Rítmica & Chaser 8 Canales",
        "categoria": "SHOW",
        "descripcion": "Secuencia rítmica de concierto con barrido de los 8 canales DMX, cálculos dinámicos de intensidad y transiciones rápidas.",
        "codigo": (
            "/* =========================================================\n"
            "   RUTINA 2: SECUENCIA RÍTMICA DE CONCIERTO (CHASER DMX)\n"
            "   ========================================================= */\n\n"
            "int pulso_base = 50;\n"
            "int ganancia = 2;\n"
            "float tempo_beat = 1.0;\n\n"
            "escena intro_ritmica {\n"
            "    int par_impar = pulso_base + 35;\n"
            "    canal 1, par_impar;\n"
            "    canal 3, par_impar;\n"
            "    canal 5, par_impar;\n"
            "    canal 7, par_impar;\n"
            "    espera tempo_beat;\n\n"
            "    int par_par = pulso_base * ganancia;\n"
            "    canal 2, par_par;\n"
            "    canal 4, par_par;\n"
            "    canal 6, par_par;\n"
            "    canal 8, par_par;\n"
            "    mezcla 2, 4;\n"
            "    mezcla 6, 8;\n"
            "    espera tempo_beat;\n"
            "}\n\n"
            "escena drop_estrobos {\n"
            "    int impacto = (30 + 20) * 2;\n"
            "    canal 1, impacto;\n"
            "    canal 4, impacto;\n"
            "    canal 8, impacto;\n"
            "    mezcla 1, 4, 100;\n"
            "    mezcla 5, 8, 90;\n"
            "    espera 1.8;\n"
            "}\n"
        ),
    },
    {
        "id": "rutina_con_error_sintaxis",
        "titulo": "3. Rutina con Error de Sintaxis (Bloqueo de Seguridad DMX)",
        "categoria": "ERROR",
        "descripcion": "Fallo de escritura en la fórmula de intensidad '(40 + * 15;' que activa el bloqueo preventivo de la consola antes de enviar señal a las luces.",
        "codigo": (
            "/* =========================================================\n"
            "   RUTINA 3: PRUEBA DE BLOQUEO POR ERROR DE SINTAXIS\n"
            "   ========================================================= */\n\n"
            "int canal_apertura = 80;\n\n"
            "escena prueba_fallo {\n"
            "    // Error de sintaxis en línea 9: operador '*' inesperado tras '+'\n"
            "    int foco_descalibrado = (40 + * 15;\n"
            "    canal 1, foco_descalibrado;\n"
            "    espera 2.0;\n"
            "}\n"
        ),
    },
    {
        "id": "rutina_con_error_logico",
        "titulo": "4. Rutina con Error Lógico / Tipos y Ámbito (Bloqueo Semántico)",
        "categoria": "ERROR",
        "descripcion": "Intento inválido de sumar un nombre de etiqueta (texto) con un nivel numérico de intensidad DMX o usar variables fuera de escena.",
        "codigo": (
            "/* =========================================================\n"
            "   RUTINA 4: PRUEBA DE BLOQUEO POR ERROR LÓGICO / SEMÁNTICO\n"
            "   ========================================================= */\n\n"
            'string nombre_preset = "Foco_Principal_Ambar";\n'
            "int nivel_dmx = 75;\n\n"
            "escena mezcla_invalida {\n"
            "    // Error lógico en línea 10: no se puede sumar texto con intensidad numérica\n"
            "    int intensidad_erronea = nombre_preset + nivel_dmx;\n"
            "    canal 1, intensidad_erronea;\n"
            "}\n"
        ),
    },
]


def obtener_presets_json() -> Dict[str, Any]:
    """Devuelve el catálogo de rutinas tanto como diccionario indexado como lista."""
    por_id = {p["id"]: p for p in PRESETS_DMX}
    return {
        "presets": PRESETS_DMX,
        "show_apertura": por_id["show_apertura"],
        "show_concierto": por_id["show_concierto"],
        "rutina_con_error_sintaxis": por_id["rutina_con_error_sintaxis"],
        "rutina_con_error_logico": por_id["rutina_con_error_logico"],
    }


# =====================================================================
# Conversión de la Ejecución IR a Línea de Tiempo Escénica DMX-8
# =====================================================================


def normalizar_porcentaje(valor_bruto: Any) -> int:
    """
    Normaliza cualquier valor numérico calculado por StageLang a un porcentaje
    de intensidad luminosa entre 0 % y 100 %:
    - Si está en 0..100, se interpreta directamente como porcentaje (0..100 %).
    - Si está en 101..255, se interpreta como nivel DMX de 8 bits y se escala a 0..100 %.
    - Si supera 255, se satura al 100 % (o se modula proporcionalmente).
    """
    if not isinstance(valor_bruto, (int, float)):
        return 75
    if valor_bruto <= 0:
        return 0
    if valor_bruto <= 100:
        return int(round(valor_bruto))
    if valor_bruto <= 255:
        return max(1, min(100, int(round((valor_bruto / 255.0) * 100))))
    return 100


def porcentaje_a_dmx(porcentaje: int) -> int:
    """Convierte un porcentaje (0..100 %) a valor DMX de 8 bits (0..255)."""
    p = max(0, min(100, porcentaje))
    return int(round((p / 100.0) * 255))


def construir_timeline_dmx(
    cuadruplas_optimizadas: List[Cuadrupla],
) -> Dict[str, Any]:
    """
    Interpreta la secuencia de cuádruplas optimizadas de StageLang y construye:
    - `eventos`: lista cronológica de acciones escénicas para la consola DMX-8:
        * `{"accion": "ESCENA_INICIO", "escena": "..."}`
        * `{"accion": "CANAL", "canal": 1..8, "intensidad": 0..100, "dmx": 0..255}`
        * `{"accion": "MEZCLA", "canal_a": 1..8, "canal_b": 1..8, "resultado": 0..100, "dmx": 0..255}`
        * `{"accion": "ESPERA", "segundos": float}`
        * `{"accion": "ESCENA_FIN", "escena": "..."}`
    - `estado_final`: estado final de los 8 canales DMX, variables calculadas y duración total.
    """
    entorno_valores: Dict[str, Any] = {}
    niveles_canales: Dict[int, int] = {ch: 0 for ch in range(1, 9)}
    eventos: List[Dict[str, Any]] = []
    escena_activa: str = "GLOBAL"
    cursor_canal_auto: int = 0
    cursor_mezcla_auto: int = 0
    duracion_total_seg: float = 0.0

    def resolver(operando: Any) -> Any:
        if operando is None or operando == "-":
            return None
        if isinstance(operando, (int, float)):
            return operando
        if isinstance(operando, str):
            if len(operando) >= 2 and operando.startswith('"') and operando.endswith('"'):
                return operando[1:-1]
            if operando in entorno_valores:
                return entorno_valores[operando]
            try:
                return float(operando) if "." in operando else int(operando)
            except ValueError:
                return operando
        return operando

    for cuad in cuadruplas_optimizadas:
        op = cuad.op

        if op == "ESCENA_INICIO":
            escena_activa = str(cuad.resultado)
            eventos.append(
                {
                    "accion": "ESCENA_INICIO",
                    "escena": escena_activa,
                }
            )
            continue

        if op == "ESCENA_FIN":
            eventos.append(
                {
                    "accion": "ESCENA_FIN",
                    "escena": str(cuad.resultado),
                }
            )
            escena_activa = "GLOBAL"
            continue

        if op == "=":
            entorno_valores[cuad.resultado] = resolver(cuad.arg1)
            continue

        if op in ("+", "-", "*", "/"):
            v1 = resolver(cuad.arg1)
            v2 = resolver(cuad.arg2)
            if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                if op == "+":
                    entorno_valores[cuad.resultado] = v1 + v2
                elif op == "-":
                    entorno_valores[cuad.resultado] = v1 - v2
                elif op == "*":
                    entorno_valores[cuad.resultado] = v1 * v2
                elif op == "/" and v2 != 0:
                    entorno_valores[cuad.resultado] = (
                        v1 // v2
                        if (isinstance(v1, int) and isinstance(v2, int) and v1 % v2 == 0)
                        else v1 / v2
                    )
            continue

        if op == "CANAL":
            val1 = resolver(cuad.arg1)
            val2 = resolver(cuad.arg2)

            if val2 is not None:
                # Sintaxis explícita de 2 argumentos: canal <num_canal>, <intensidad>;
                num_canal = int(round(float(val1))) if isinstance(val1, (int, float)) else 1
                num_canal = ((num_canal - 1) % 8) + 1
                intensidad_pct = normalizar_porcentaje(val2)
            else:
                # Sintaxis de 1 argumento: canal <intensidad>; -> asigna canal rotativo 1..8
                num_canal = (cursor_canal_auto % 8) + 1
                cursor_canal_auto += 1
                intensidad_pct = normalizar_porcentaje(val1)

            niveles_canales[num_canal] = intensidad_pct
            eventos.append(
                {
                    "accion": "CANAL",
                    "canal": num_canal,
                    "intensidad": intensidad_pct,
                    "dmx": porcentaje_a_dmx(intensidad_pct),
                    "escena": escena_activa,
                }
            )
            continue

        if op == "MEZCLA":
            val1 = resolver(cuad.arg1)
            val2 = resolver(cuad.arg2)
            val3 = resolver(cuad.resultado)

            if val2 is not None and isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
                # Sintaxis multi-argumento: mezcla <canal_a>, <canal_b> [, <resultado>];
                canal_a = ((int(round(float(val1))) - 1) % 8) + 1
                canal_b = ((int(round(float(val2))) - 1) % 8) + 1
                if val3 is not None and isinstance(val3, (int, float)):
                    resultado_pct = normalizar_porcentaje(val3)
                else:
                    int_a = niveles_canales.get(canal_a, 70)
                    int_b = niveles_canales.get(canal_b, 70)
                    resultado_pct = max(25, min(100, int(round((int_a + int_b) / 2.0))))
                etiqueta_mezcla = f"CH{canal_a} + CH{canal_b}"
            else:
                # Sintaxis de 1 argumento: mezcla "Nombre_Preset" o mezcla <valor>;
                canal_a = (cursor_mezcla_auto % 8) + 1
                canal_b = ((cursor_mezcla_auto + 1) % 8) + 1
                cursor_mezcla_auto += 2
                if isinstance(val1, (int, float)):
                    resultado_pct = normalizar_porcentaje(val1)
                else:
                    int_a = niveles_canales.get(canal_a, 80) or 80
                    int_b = niveles_canales.get(canal_b, 60) or 60
                    resultado_pct = max(35, min(100, int(round((int_a + int_b) / 2.0))))
                etiqueta_mezcla = str(val1)

            niveles_canales[canal_a] = resultado_pct
            niveles_canales[canal_b] = resultado_pct
            eventos.append(
                {
                    "accion": "MEZCLA",
                    "canal_a": canal_a,
                    "canal_b": canal_b,
                    "resultado": resultado_pct,
                    "dmx": porcentaje_a_dmx(resultado_pct),
                    "etiqueta": etiqueta_mezcla,
                    "escena": escena_activa,
                }
            )
            continue

        if op == "ESPERA":
            val1 = resolver(cuad.arg1)
            val_num = float(val1) if isinstance(val1, (int, float)) else 1.5
            # Si el usuario escribió milisegundos o unidades grandes (ej. 52.5 o 132.0),
            # las escalamos suavemente a segundos escénicos (0.5s .. 4.0s)
            if val_num > 10.0:
                segundos = round(max(0.8, min(3.5, val_num / 35.0)), 2)
            else:
                segundos = round(max(0.3, min(8.0, val_num)), 2)

            duracion_total_seg = round(duracion_total_seg + segundos, 2)
            eventos.append(
                {
                    "accion": "ESPERA",
                    "segundos": segundos,
                    "valor_original": val_num,
                    "escena": escena_activa,
                }
            )
            continue

    variables_usuario = {
        k: v
        for k, v in entorno_valores.items()
        if not (k.startswith("t") and k[1:].isdigit())
    }

    return {
        "eventos": eventos,
        "estado_final": {
            "canales": {
                str(ch): {
                    "intensidad": pct,
                    "dmx": porcentaje_a_dmx(pct),
                }
                for ch, pct in niveles_canales.items()
            },
            "variables": variables_usuario,
            "total_eventos": len(eventos),
            "duracion_total_segundos": duracion_total_seg,
        },
    }


def extraer_linea_de_error(exc: Exception) -> Optional[int]:
    """Obtiene el número de línea desde la excepción del compilador o su mensaje."""
    linea = getattr(exc, "linea", None)
    if isinstance(linea, int) and linea > 0:
        return linea
    m = re.search(r"L:(\d+)", str(exc))
    if m:
        return int(m.group(1))
    return None


def formatear_alerta_consola(exc: Exception, tipo_fallo: str) -> str:
    """Formatea un mensaje de alerta claro indicando la línea exacta del fallo."""
    linea = extraer_linea_de_error(exc)
    texto_limpio = str(exc)
    if linea and f"línea {linea}" not in texto_limpio.lower():
        return f"Error en línea {linea} ({tipo_fallo}): {texto_limpio}"
    return f"Error ({tipo_fallo}): {texto_limpio}"


def ejecutar_show_dmx(codigo_fuente: str) -> Dict[str, Any]:
    """
    Ejecuta el pipeline completo de StageLang (`FrontEnd` -> `MiddleEnd` -> `BackEnd`)
    para validar y calcular la rutina escénica solicitada por `/api/ejecutar-show`.
    """
    if not codigo_fuente or not codigo_fuente.strip():
        return {
            "ok": False,
            "alerta": "Error en línea 1: La rutina StageLang está vacía.",
            "tipo_fallo": "ENTRADA_VACIA",
            "linea": 1,
        }

    try:
        # 1. Front-End: Léxico, Sintáctico y Semántico
        res_fe = FrontEnd().ejecutar(codigo_fuente)

        # 2. Middle-End: Generación TAC y Optimización
        res_me = MiddleEnd().ejecutar(res_fe.ast)

        # 3. Back-End: Emulación en GestorMemoria (Stack/Heap) y validación de ejecución
        res_be = BackEnd().ejecutar(
            ir_optimizada=res_me.ir_optimizada,
            tabla_simbolos=res_fe.tabla_simbolos,
        )

        # 4. Construcción de la línea de tiempo escénica para la mesa DMX-8
        timeline = construir_timeline_dmx(res_me.ir_optimizada)
        timeline["estado_final"]["variables_globales_memoria"] = res_be.variables_globales_finales

        return {
            "ok": True,
            "eventos": timeline["eventos"],
            "estado_final": timeline["estado_final"],
        }

    except ErrorLexico as exc:
        return {
            "ok": False,
            "alerta": formatear_alerta_consola(exc, "FALLO LÉXICO"),
            "tipo_fallo": "LEXICO",
            "linea": extraer_linea_de_error(exc),
        }
    except ErrorSintactico as exc:
        return {
            "ok": False,
            "alerta": formatear_alerta_consola(exc, "FALLO DE SINTAXIS"),
            "tipo_fallo": "SINTACTICO",
            "linea": extraer_linea_de_error(exc),
        }
    except ErrorSemantico as exc:
        return {
            "ok": False,
            "alerta": formatear_alerta_consola(exc, "FALLO LÓGICO / SEMÁNTICO"),
            "tipo_fallo": "SEMANTICO",
            "linea": extraer_linea_de_error(exc),
        }
    except (ErrorEjecucionIR, ErrorMemoria) as exc:
        return {
            "ok": False,
            "alerta": formatear_alerta_consola(exc, "FALLO DE EJECUCIÓN / MEMORIA"),
            "tipo_fallo": "RUNTIME_MEMORIA",
            "linea": extraer_linea_de_error(exc),
        }


# =====================================================================
# Servidor HTTP Nativo (`http.server`)
# =====================================================================


class StageLangDMXHandler(BaseHTTPRequestHandler):
    """Manejador HTTP para la Consola Escénica STAGELANG DMX-8."""

    def _enviar_json(self, datos: Dict[str, Any], status: int = HTTPStatus.OK) -> None:
        cuerpo = json.dumps(datos, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _enviar_html(self, html: str, status: int = HTTPStatus.OK) -> None:
        cuerpo = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self) -> None:  # noqa: N802
        ruta = urllib.parse.urlparse(self.path).path

        if ruta in ("/", "/index.html"):
            if not RUTA_INDEX_HTML.exists():
                self._enviar_html(
                    "<h1>Error: No se encontró ui/index.html</h1>",
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._enviar_html(RUTA_INDEX_HTML.read_text(encoding="utf-8"))
            return

        if ruta in ("/api/presets", "/api/ejemplos"):
            self._enviar_json(obtener_presets_json())
            return

        self._enviar_json(
            {"ok": False, "alerta": f"Ruta no encontrada: {ruta}"},
            status=HTTPStatus.NOT_FOUND,
        )

    def do_POST(self) -> None:  # noqa: N802
        ruta = urllib.parse.urlparse(self.path).path

        if ruta in ("/api/ejecutar-show", "/api/compilar"):
            try:
                longitud = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(longitud) if longitud > 0 else b"{}"
                payload = json.loads(raw.decode("utf-8"))
            except Exception as exc:
                self._enviar_json(
                    {
                        "ok": False,
                        "alerta": f"Solicitud JSON inválida: {exc}",
                        "tipo_fallo": "SOLICITUD_INVALIDA",
                    },
                    status=HTTPStatus.BAD_REQUEST,
                )
                return

            codigo = str(payload.get("codigo", ""))
            resultado = ejecutar_show_dmx(codigo)
            self._enviar_json(resultado)
            return

        self._enviar_json(
            {"ok": False, "alerta": f"Endpoint POST no encontrado: {ruta}"},
            status=HTTPStatus.NOT_FOUND,
        )

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        print(f"  [DMX-8 HTTP] {self.address_string()} - {format % args}")


def iniciar_servidor(
    host: str = "localhost",
    puerto: int = 8000,
    abrir_navegador: bool = True,
) -> None:
    """Inicia el servidor de la consola STAGELANG DMX-8 en http://localhost:8000."""
    servidor = ThreadingHTTPServer((host, puerto), StageLangDMXHandler)
    url = f"http://{host}:{puerto}"

    print("=" * 88)
    print("  STAGELANG DMX-8 — CONTROLADOR DE ILUMINACIÓN, MEZCLA Y TEMPORIZACIÓN ESCÉNICA")
    print("=" * 88)
    print(f"  Mesa DMX Activa en : {url}")
    print(f"  Interfaz Web       : {RUTA_INDEX_HTML}")
    print("  Endpoints REST     : GET /  |  GET /api/presets  |  POST /api/ejecutar-show")
    print("  Presiona Ctrl+C para apagar la consola.")
    print("=" * 88)

    if abrir_navegador:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Apagando consola STAGELANG DMX-8...")
    finally:
        servidor.server_close()


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(
        description="Inicia la consola web STAGELANG DMX-8 en http://localhost:8000"
    )
    arg_parser.add_argument("--host", default="localhost", help="Host local (default: localhost)")
    arg_parser.add_argument("--port", type=int, default=8000, help="Puerto HTTP (default: 8000)")
    arg_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="No abrir automáticamente el navegador",
    )
    args = arg_parser.parse_args()
    iniciar_servidor(
        host=args.host,
        puerto=args.port,
        abrir_navegador=not args.no_browser,
    )
