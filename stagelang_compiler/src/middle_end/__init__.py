"""
Macro-Fase 2: Middle-End del Compilador StageLang.
Agrupa la generación/emulación de Representación Intermedia TAC (`ir_tac.py`)
y la optimización de cuádruplas (`optimizador.py`).
"""

from .ir_tac import (
    Cuadrupla,
    GeneradorTAC,
    EmuladorVirtualIR,
    ErrorEjecucionIR,
    formatear_tabla_cuadruplas,
)
from .optimizador import (
    ReporteOptimizacion,
    OptimizadorTAC,
    optimizar_cuadruplas,
)

__all__ = [
    "Cuadrupla",
    "GeneradorTAC",
    "EmuladorVirtualIR",
    "ErrorEjecucionIR",
    "formatear_tabla_cuadruplas",
    "ReporteOptimizacion",
    "OptimizadorTAC",
    "optimizar_cuadruplas",
]
