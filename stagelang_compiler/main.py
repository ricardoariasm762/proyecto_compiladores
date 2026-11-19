"""
Orquestador Principal del Compilador StageLang (`main.py`).

Demuestra la arquitectura explícita por Macro-Fases definida en `src/pipeline.py`:
- `=== FASE 1: FRONT-END (ANÁLISIS LÉXICO, SINTÁCTICO Y SEMÁNTICO) ===`
- `=== FASE 2: MIDDLE-END (REPRESENTACIÓN INTERMEDIA TAC Y OPTIMIZACIÓN) ===`
- `=== FASE 3: BACK-END (MEMORIA STACK/HEAP Y CÓDIGO OBJETIVO / REGISTROS) ===`

Y ejecuta a continuación la batería completa de pruebas de estrés y defensa del compilador
(`pruebas/estres_errores.stagelang`, Doble free en Heap, División por cero en IR y saturación
de registros físicos `R0, R1, R2` con Spill a Stack `0x2000+`).
"""

from pathlib import Path
from typing import Dict, List

from src.frontend import (
    AnalizadorSemantico,
    ErrorLexico,
    ErrorSemantico,
    ErrorSintactico,
    Parser,
    formatear_ast,
    tokenizar,
)
from src.middle_end import (
    EmuladorVirtualIR,
    ErrorEjecucionIR,
    GeneradorTAC,
    formatear_tabla_cuadruplas,
)
from src.backend import (
    ErrorMemoria,
    GeneradorCodigoObjetivo,
    GestorMemoria,
)
from src.pipeline import BackEnd, FrontEnd, MiddleEnd


SEPARADOR = "=" * 98
SUBSEPARADOR = "-" * 98


def imprimir_banner(titulo: str) -> None:
    print(f"\n{SEPARADOR}")
    print(f"  {titulo}")
    print(SEPARADOR)


def ejecutar_flujo_valido(ruta_archivo: Path) -> None:
    """
    Ejecuta el flujo válido completo a través de las clases `FrontEnd`, `MiddleEnd` y `BackEnd`
    de `src/pipeline.py`, mostrando los encabezados y artefactos de cada macro-fase.
    """
    codigo_fuente = ruta_archivo.read_text(encoding="utf-8")

    imprimir_banner(f"DEMOSTRACIÓN DEL PIPELINE COMPLETO STAGELANG ({ruta_archivo.name})")
    print("\n[CÓDIGO FUENTE DE ENTRADA]:")
    print(SUBSEPARADOR)
    for num, linea in enumerate(codigo_fuente.splitlines(), start=1):
        print(f"  {num:02d} | {linea}")

    # =====================================================================
    # MACRO-FASE 1: FRONT-END
    # =====================================================================
    print(f"\n{SEPARADOR}")
    print("=== FASE 1: FRONT-END (ANÁLISIS LÉXICO, SINTÁCTICO Y SEMÁNTICO) ===")
    print(SEPARADOR)

    frontend = FrontEnd()
    res_fe = frontend.ejecutar(codigo_fuente)

    print(f"\n[1.1] Análisis Léxico: {len(res_fe.tokens)} tokens generados (comentarios filtrados como SKIP):")
    for idx, tok in enumerate(res_fe.tokens, start=1):
        print(f"  {idx:03d}. {tok}")

    print("\n[1.2] Análisis Sintáctico (Gramática EBNF Top-Down) - Árbol de Sintaxis Abstracta (AST):")
    print(formatear_ast(res_fe.ast))

    print("\n[1.3] Evaluación Recursiva del AST en Post-Orden (Tree Walking):")
    for traza in res_fe.traza_evaluacion_ast:
        print(f"  {traza}")

    print("\n[1.4] Análisis Semántico - Tabla de Símbolos Jerárquica (GLOBAL -> escena_*):")
    print(res_fe.tabla_simbolos.resumen_tabla())

    print("\n[1.5] Inferencia y Chequeo de Tipos (incluyendo coerciones implícitas INT -> FLOAT):")
    for decision in res_fe.decisiones_tipos:
        print(f"  * {decision}")

    # =====================================================================
    # MACRO-FASE 2: MIDDLE-END
    # =====================================================================
    print(f"\n{SEPARADOR}")
    print("=== FASE 2: MIDDLE-END (REPRESENTACIÓN INTERMEDIA TAC Y OPTIMIZACIÓN) ===")
    print(SEPARADOR)

    middle_end = MiddleEnd()
    res_me = middle_end.ejecutar(res_fe.ast)

    print(f"\n[2.1] Código de Tres Direcciones (TAC / Cuádruplas Crudas: {len(res_me.ir_cruda)} instrucciones):")
    print(formatear_tabla_cuadruplas(res_me.ir_cruda))

    print("\n[2.2] Pasada de Optimización (Plegado/Propagación de Constantes y Temporales Muertos):")
    for log_opt in res_me.reporte_optimizacion.bitacora_transformaciones:
        print(f"  * {log_opt}")

    rep = res_me.reporte_optimizacion
    print(
        f"\nMétrica de Reducción de IR: {rep.total_antes} cuádruplas -> "
        f"{rep.total_despues} cuádruplas (reducción del {rep.porcentaje_reduccion:.1f}%)\n"
    )
    print("[2.3] Tabla de Cuádruplas Optimizada:")
    print(formatear_tabla_cuadruplas(res_me.ir_optimizada))

    # =====================================================================
    # MACRO-FASE 3: BACK-END
    # =====================================================================
    print(f"\n{SEPARADOR}")
    print("=== FASE 3: BACK-END (MEMORIA STACK/HEAP Y CÓDIGO OBJETIVO / REGISTROS) ===")
    print(SEPARADOR)

    backend = BackEnd(registros_fisicos=["R0", "R1", "R2"])
    res_be = backend.ejecutar(
        ir_optimizada=res_me.ir_optimizada,
        tabla_simbolos=res_fe.tabla_simbolos,
    )

    print("\n[3.1] Traza del EmuladorVirtualIR integrado con GestorMemoria (Stack Frames LIFO & Heap):")
    for ev in res_be.eventos_emulacion_ir:
        print(f"  {ev}")

    print("\n[3.2] Bitácora Detallada de Operaciones en Stack Frames (0x7000+) y Heap Dinámico (0x1000+):")
    for entrada in res_be.gestor_memoria.bitacora:
        print(f"  {entrada}")

    print(f"\n[3.3] Estado de Memoria al Finalizar la Emulación:\n{res_be.gestor_memoria.estado_actual()}")

    res_cg = res_be.resultado_codegen
    print("\n[3.4] Análisis de Tiempo de Vida (Liveness / Último Índice de Uso en IR Optimizada):")
    for simbolo, ult_idx in res_cg.tabla_ultimo_uso.items():
        tipo_s = "Temporal" if (simbolo.startswith("t") and simbolo[1:].isdigit()) else "Variable"
        print(f"  - {tipo_s:<8} {simbolo:<18} -> último uso en cuádrupla #{ult_idx}")

    print("\n[3.5] Traza del Asignador de Registros Físicos (R0, R1, R2) por Liveness y Spill:")
    for ev_reg in res_cg.eventos_registros:
        print(f"  {ev_reg}")

    if res_cg.mapa_spill:
        print("\n[3.6] Mapa de Spills a Memoria de Stack (0x2000+):")
        for simb, dir_hex in res_cg.mapa_spill.items():
            print(f"  * {simb:<12} -> volcado en [{dir_hex}]")

    print("\n[3.7] Código Objetivo / Ensamblador Generado:")
    print(SUBSEPARADOR)
    for linea_asm in res_cg.instrucciones_asm:
        print(linea_asm)


def extraer_casos_estres(ruta_archivo: Path) -> Dict[str, str]:
    """Separa los casos de `pruebas/estres_errores.stagelang` marcados con `// ---CASO:`."""
    texto = ruta_archivo.read_text(encoding="utf-8")
    casos: Dict[str, str] = {}
    titulo_actual = ""
    lineas_actuales: List[str] = []

    for linea in texto.splitlines():
        if linea.strip().startswith("// ---CASO:"):
            if titulo_actual:
                casos[titulo_actual] = "\n".join(lineas_actuales).strip()
            titulo_actual = linea.strip().replace("// ---CASO:", "").strip(" -")
            lineas_actuales = [linea]
        elif titulo_actual:
            lineas_actuales.append(linea)

    if titulo_actual and lineas_actuales:
        casos[titulo_actual] = "\n".join(lineas_actuales).strip()

    return casos


def ejecutar_pruebas_estres(ruta_archivo: Path) -> None:
    """
    Ejecuta la batería de pruebas de estrés y manejo riguroso de errores sin colapsos.
    """
    imprimir_banner(
        f"BATERÍA DE PRUEBAS DE ESTRÉS Y DEFENSA DEL COMPILADOR ({ruta_archivo.name})"
    )

    frontend = FrontEnd()
    casos = extraer_casos_estres(ruta_archivo)

    for titulo, codigo_caso in casos.items():
        print(f"\n{SUBSEPARADOR}")
        print(f"  ESCENARIO: {titulo}")
        print(SUBSEPARADOR)
        for idx, l in enumerate(codigo_caso.splitlines(), start=1):
            print(f"  {idx:02d} | {l}")

        try:
            frontend.ejecutar(codigo_caso)
            print("  [RESULTADO INESPERADO] El caso no lanzó excepción.")
        except (ErrorLexico, ErrorSintactico, ErrorSemantico) as exc:
            print(f"\n  [EXCEPCIÓN CAPTURADA LIMPIAMENTE - {type(exc).__name__}]:")
            for linea_err in str(exc).splitlines():
                print(f"    {linea_err}")

    # -----------------------------------------------------------------
    # Caso 5: Redeclaración duplicada en el mismo ámbito
    # -----------------------------------------------------------------
    print(f"\n{SUBSEPARADOR}")
    print("  ESCENARIO: 5. Error Semántico por Redeclaración Duplicada en el Mismo Ámbito")
    print(SUBSEPARADOR)
    codigo_redecl = "int canal_strobe = 5;\nint canal_strobe = 12;\n"
    for idx, l in enumerate(codigo_redecl.strip().splitlines(), start=1):
        print(f"  {idx:02d} | {l}")
    try:
        frontend.ejecutar(codigo_redecl)
    except ErrorSemantico as exc:
        print(f"\n  [EXCEPCIÓN CAPTURADA LIMPIAMENTE - {type(exc).__name__}]:")
        print(f"    {exc}")

    # -----------------------------------------------------------------
    # Caso 6: División por Cero en EmuladorVirtualIR
    # -----------------------------------------------------------------
    print(f"\n{SUBSEPARADOR}")
    print("  ESCENARIO: 6. Error en Tiempo de Ejecución IR (División por Cero)")
    print(SUBSEPARADOR)
    codigo_div_cero = (
        "int numerador = 100;\n"
        "int divisor = 0;\n"
        "int fallo = numerador / divisor;\n"
    )
    for idx, l in enumerate(codigo_div_cero.strip().splitlines(), start=1):
        print(f"  {idx:02d} | {l}")
    try:
        res_fe = frontend.ejecutar(codigo_div_cero)
        res_me = MiddleEnd().ejecutar(res_fe.ast)
        BackEnd().ejecutar(res_me.ir_optimizada, res_fe.tabla_simbolos)
    except ErrorEjecucionIR as exc:
        print(f"\n  [EXCEPCIÓN CAPTURADA LIMPIAMENTE - {type(exc).__name__}]:")
        print(f"    {exc}")

    # -----------------------------------------------------------------
    # Caso 7: Detección Explícita de Doble Free en Heap Dinámico
    # -----------------------------------------------------------------
    print(f"\n{SUBSEPARADOR}")
    print("  ESCENARIO: 7. Violación de Seguridad en Memoria Dinámica (Doble Free en Heap)")
    print(SUBSEPARADOR)
    gestor_estres = GestorMemoria(auto_iniciar_global=True)
    try:
        dir_recurso = gestor_estres.reservar_heap(
            etiqueta="Textura_Proyeccion_Laser",
            datos="frame_buffer_4k",
            tamano_bytes=128,
        )
        print(f"  1) Reserva inicial en Heap exitosa -> dirección {dir_recurso}")
        gestor_estres.liberar_heap(dir_recurso)
        print(f"  2) Primera liberación (free) de {dir_recurso} completada sin errores.")
        print(f"  3) Intentando liberar por segunda vez la dirección {dir_recurso}...")
        gestor_estres.liberar_heap(dir_recurso)
    except ErrorMemoria as exc:
        print(f"\n  [EXCEPCIÓN CAPTURADA LIMPIAMENTE - {type(exc).__name__}]:")
        print(f"    {exc}")

    # -----------------------------------------------------------------
    # Caso 8: Estrés de Saturación de Registros (R0, R1, R2) con Liveness + Spill
    # -----------------------------------------------------------------
    print(f"\n{SUBSEPARADOR}")
    print("  ESCENARIO: 8. Estrés de Registros Físicos (R0, R1, R2) con Liveness y Spill a [0x2000+]")
    print(SUBSEPARADOR)
    codigo_spill = (
        "int v1 = 10;\n"
        "int v2 = 20;\n"
        "int v3 = 30;\n"
        "int v4 = 40;\n"
        "int mega_mezcla = ((v1 + v2) * (v3 + v4)) + ((v1 * v3) - ((v2 + v4) * (v3 - v1)));\n"
        "canal mega_mezcla;\n"
    )
    for idx, l in enumerate(codigo_spill.strip().splitlines(), start=1):
        print(f"  {idx:02d} | {l}")

    tokens_s = tokenizar(codigo_spill)
    ast_s = Parser(tokens_s).parse()
    AnalizadorSemantico().analizar(ast_s)
    cuads_s = GeneradorTAC().generar(ast_s)
    res_spill = GeneradorCodigoObjetivo(registros_fisicos=["R0", "R1", "R2"]).generar(cuads_s)

    print("\nTraza de Liveness y Spill del Asignador sobre ['R0', 'R1', 'R2']:")
    for ev in res_spill.eventos_registros:
        print(f"  {ev}")

    print("\nCódigo Ensamblador con STORE/LOAD de Spill en [0x2000+]:")
    for linea_asm in res_spill.instrucciones_asm:
        print(linea_asm)


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    ruta_valido = base_dir / "pruebas" / "flujo_valido.stagelang"
    ruta_estres = base_dir / "pruebas" / "estres_errores.stagelang"

    ejecutar_flujo_valido(ruta_valido)
    ejecutar_pruebas_estres(ruta_estres)

    imprimir_banner("EJECUCIÓN COMPLETADA EXITOSAMENTE - STAGELANG COMPILER")


if __name__ == "__main__":
    main()
