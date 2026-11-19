"""
Orquestador del Pipeline por Macro-Fases del Compilador StageLang (`src/pipeline.py`).

Encapsula explícitamente las tres macro-fases arquitectónicas del compilador:
1. `FrontEnd`:
   Recibe el código fuente en texto plano, ejecuta `tokenizar() -> Parser.parse() ->
   AnalizadorSemantico.analizar()`, y retorna el AST validado junto con la `SymbolTable`
   y la evaluación preliminar en post-orden.
2. `MiddleEnd`:
   Recibe el AST validado, genera las cuádruplas TAC (`GeneradorTAC`) y ejecuta el
   optimizador (`optimizar_cuadruplas`), retornando la IR cruda y la IR optimizada.
3. `BackEnd`:
   Recibe la IR optimizada y la `SymbolTable`, ejecuta la simulación en memoria real
   (`EmuladorVirtualIR` integrado con `GestorMemoria` para Stack Frames LIFO y Heap Dinámico)
   y traduce las cuádruplas a ensamblador (`GeneradorCodigoObjetivo` con análisis de *liveness*
   y *Spill* sobre `R0, R1, R2`).
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .frontend import (
    AnalizadorSemantico,
    Parser,
    ProgramaNode,
    SymbolTable,
    Token,
    evaluar_ast,
    tokenizar,
)
from .middle_end import (
    Cuadrupla,
    EmuladorVirtualIR,
    GeneradorTAC,
    ReporteOptimizacion,
    optimizar_cuadruplas,
)
from .backend import (
    GeneradorCodigoObjetivo,
    GestorMemoria,
    ResultadoCodegen,
)


@dataclass
class ResultadoFrontEnd:
    """Salida estructurada de la Macro-Fase 1 (Front-End)."""

    tokens: List[Token]
    ast: ProgramaNode
    tabla_simbolos: SymbolTable
    decisiones_tipos: List[str]
    traza_evaluacion_ast: List[str]


@dataclass
class ResultadoMiddleEnd:
    """Salida estructurada de la Macro-Fase 2 (Middle-End)."""

    ir_cruda: List[Cuadrupla]
    ir_optimizada: List[Cuadrupla]
    reporte_optimizacion: ReporteOptimizacion


@dataclass
class ResultadoBackEnd:
    """Salida estructurada de la Macro-Fase 3 (Back-End)."""

    gestor_memoria: GestorMemoria
    eventos_emulacion_ir: List[str]
    variables_globales_finales: Dict[str, Any]
    resultado_codegen: ResultadoCodegen


class FrontEnd:
    """
    Macro-Fase 1: Análisis (dependiente del lenguaje fuente StageLang).
    Ejecuta Análisis Léxico -> Análisis Sintáctico (AST) -> Análisis Semántico (Ámbitos y Tipos).
    """

    def ejecutar(self, codigo_fuente: str) -> ResultadoFrontEnd:
        tokens = tokenizar(codigo_fuente)
        parser = Parser(tokens)
        ast_validado = parser.parse()

        analizador_semantico = AnalizadorSemantico()
        tabla_simbolos = analizador_semantico.analizar(ast_validado)

        try:
            eval_postorden = evaluar_ast(ast_validado)
            traza_ast = list(eval_postorden["traza"])
        except ZeroDivisionError as exc:
            traza_ast = [f"[AVISO EVALUADOR AST] {exc} (será validado en EmuladorVirtualIR)"]

        return ResultadoFrontEnd(
            tokens=tokens,
            ast=ast_validado,
            tabla_simbolos=tabla_simbolos,
            decisiones_tipos=list(analizador_semantico.decisiones_tipos),
            traza_evaluacion_ast=traza_ast,
        )


class MiddleEnd:
    """
    Macro-Fase 2: Representación Intermedia (TAC / Cuádruplas) y Optimización Independiente de Máquina.
    Genera el Código de Tres Direcciones y aplica plegado/propagación de constantes y eliminación
    de temporales muertos.
    """

    def ejecutar(self, ast_validado: ProgramaNode) -> ResultadoMiddleEnd:
        generador_tac = GeneradorTAC()
        ir_cruda = generador_tac.generar(ast_validado)
        reporte_opt = optimizar_cuadruplas(ir_cruda)

        return ResultadoMiddleEnd(
            ir_cruda=ir_cruda,
            ir_optimizada=reporte_opt.cuadruplas_optimizadas,
            reporte_optimizacion=reporte_opt,
        )


class BackEnd:
    """
    Macro-Fase 3: Síntesis, Gestión de Memoria (Stack Frames LIFO / Heap) y Generación de Código Objetivo.
    Integra `EmuladorVirtualIR` con `GestorMemoria` y traduce la IR a ensamblador administrando
    los registros físicos `['R0', 'R1', 'R2']` por tiempo de vida (*liveness*) y *Spill*.
    """

    def __init__(self, registros_fisicos: Optional[List[str]] = None) -> None:
        self.registros_fisicos = (
            list(registros_fisicos) if registros_fisicos else ["R0", "R1", "R2"]
        )

    def ejecutar(
        self,
        ir_optimizada: List[Cuadrupla],
        tabla_simbolos: Optional[SymbolTable] = None,
    ) -> ResultadoBackEnd:
        gestor_memoria = GestorMemoria()
        emulador = EmuladorVirtualIR(gestor_memoria=gestor_memoria)
        variables_finales = emulador.ejecutar(
            ir_optimizada,
            gestor_memoria=gestor_memoria,
            tabla_simbolos=tabla_simbolos,
        )

        codegen = GeneradorCodigoObjetivo(registros_fisicos=self.registros_fisicos)
        resultado_codegen = codegen.generar(ir_optimizada)

        return ResultadoBackEnd(
            gestor_memoria=gestor_memoria,
            eventos_emulacion_ir=list(emulador.eventos_escena),
            variables_globales_finales=variables_finales,
            resultado_codegen=resultado_codegen,
        )
