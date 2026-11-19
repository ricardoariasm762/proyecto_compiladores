"""
Macro-Fase 3: Back-End del Compilador StageLang.
Agrupa la gestión de memoria en tiempo de ejecución (`memoria.py`: Stack Frames LIFO y Heap Dinámico)
y la generación de código objetivo con asignación de registros por *liveness* y *Spill* (`codegen.py`).
"""

from .memoria import (
    ErrorMemoria,
    VariableLocalSlot,
    StackFrame,
    BloqueHeap,
    GestorMemoria,
)
from .codegen import (
    ResultadoCodegen,
    GeneradorCodigoObjetivo,
)

__all__ = [
    "ErrorMemoria",
    "VariableLocalSlot",
    "StackFrame",
    "BloqueHeap",
    "GestorMemoria",
    "ResultadoCodegen",
    "GeneradorCodigoObjetivo",
]
