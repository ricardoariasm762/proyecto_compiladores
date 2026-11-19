"""
Macro-Fase 1: Front-End del Compilador StageLang.
Agrupa el análisis léxico (`lexer.py`), sintáctico (`parser.py`) y semántico (`semantico.py`).
"""

from .lexer import Token, ErrorLexico, tokenizar
from .parser import (
    ASTNode,
    ProgramaNode,
    EscenaNode,
    DeclaracionNode,
    AsignacionNode,
    ComandoEscenaNode,
    NumberNode,
    StringNode,
    VarNode,
    BinOpNode,
    ErrorSintactico,
    Parser,
    evaluar_ast,
    formatear_ast,
)
from .semantico import (
    Symbol,
    Scope,
    SymbolTable,
    AnalizadorSemantico,
    ErrorSemantico,
)

__all__ = [
    "Token",
    "ErrorLexico",
    "tokenizar",
    "ASTNode",
    "ProgramaNode",
    "EscenaNode",
    "DeclaracionNode",
    "AsignacionNode",
    "ComandoEscenaNode",
    "NumberNode",
    "StringNode",
    "VarNode",
    "BinOpNode",
    "ErrorSintactico",
    "Parser",
    "evaluar_ast",
    "formatear_ast",
    "Symbol",
    "Scope",
    "SymbolTable",
    "AnalizadorSemantico",
    "ErrorSemantico",
]
