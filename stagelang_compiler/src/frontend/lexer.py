"""
Fase 1.1 (Front-End): Análisis Léxico (Scanner / Tokenizer) para StageLang.

Este módulo transforma el código fuente plano en una secuencia de tokens
clasificados con información exacta de línea y columna (L:x, C:y).
Utiliza expresiones regulares con Named Groups (?P<NOMBRE>PATRON) respetando
una prioridad estricta para evitar ambigüedades léxicas.
"""

from dataclasses import dataclass
import re
from typing import List, Tuple


class ErrorLexico(Exception):
    """Excepción controlada lanzada cuando se detectan uno o más errores léxicos."""

    def __init__(self, errores: List[str]) -> None:
        self.errores = errores
        mensaje = "Se encontraron errores léxicos:\n  - " + "\n  - ".join(errores)
        super().__init__(mensaje)


@dataclass(frozen=True)
class Token:
    """
    Representa una unidad léxica mínima (Token) de StageLang.

    Atributos:
        tipo: Categoría léxica (ej. 'KW_ESCENA', 'ID', 'FLOAT', 'INT', 'PLUS').
        valor: Lexema original extraído del código fuente.
        linea: Número de línea (1-indexado).
        columna: Número de columna (1-indexado).
    """

    tipo: str
    valor: str
    linea: int
    columna: int

    def __repr__(self) -> str:
        return f"Token({self.tipo:<14}, {self.valor!r:<18}, L:{self.linea}, C:{self.columna})"


# Especificación léxica con prioridad estricta de arriba hacia abajo:
# 1. Comentarios multilínea y de una línea (SKIP) y saltos de línea.
# 2. Palabras reservadas (con límite de palabra \b) ANTES que identificadores (ID).
# 3. Literales de cadena (STRING_LITERAL) y numéricos: FLOAT (\d+\.\d+) ANTES que INT (\d+).
# 4. Operadores compuestos (&&, ||, ==, !=, <=, >=) ANTES que operadores simples (!, <, >, =).
# 5. Delimitadores [();{}] y operadores aritméticos [+\-*/].
# 6. Identificadores generales (ID).
# 7. Regla comodín ERROR (.) para capturar cualquier carácter ilegal sin abortar a mitad del escaneo.
ESPECIFICACION_TOKENS: List[Tuple[str, str]] = [
    # Comentarios y espacios (etiquetados como SKIP / NEWLINE)
    ("COMMENT_MULTI", r"/\*[\s\S]*?\*/"),
    ("COMMENT_SINGLE", r"//[^\n]*"),
    ("NEWLINE", r"\n"),
    ("SKIP", r"[ \t\r]+"),
    # Palabras reservadas del dominio StageLang y tipos de datos (antes que ID)
    ("KW_ESCENA", r"\bescena\b"),
    ("KW_CANAL", r"\bcanal\b"),
    ("KW_ESPERA", r"\bespera\b"),
    ("KW_MEZCLA", r"\bmezcla\b"),
    ("KW_INT", r"\bint\b"),
    ("KW_FLOAT", r"\bfloat\b"),
    ("KW_STRING", r"\bstring\b"),
    # Literales de cadena entre comillas dobles
    ("STRING_LITERAL", r'"[^"\n]*"'),
    # Literales numéricos: FLOAT estrictamente antes que INT
    ("FLOAT", r"\d+\.\d+"),
    ("INT", r"\d+"),
    # Operadores lógicos y relacionales compuestos antes que simples y asignación '='
    ("AND", r"&&"),
    ("OR", r"\|\|"),
    ("EQ", r"=="),
    ("NEQ", r"!="),
    ("LTE", r"<="),
    ("GTE", r">="),
    ("NOT", r"!"),
    ("LT", r"<"),
    ("GT", r">"),
    ("ASSIGN", r"="),
    # Operadores aritméticos
    ("PLUS", r"\+"),
    ("MINUS", r"-"),
    ("MUL", r"\*"),
    ("DIV", r"/"),
    # Delimitadores
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("LBRACE", r"\{"),
    ("RBRACE", r"\}"),
    ("SEMICOLON", r";"),
    ("COMMA", r","),
    # Identificadores (después de palabras reservadas)
    ("ID", r"[a-zA-Z_][a-zA-Z0-9_]*"),
    # Captura de caracteres ilegales
    ("ERROR", r"."),
]

# Compilación de la expresión regular maestra con Named Groups (?P<NOMBRE>PATRON)
PATRON_MAESTRO = re.compile(
    "|".join(f"(?P<{nombre}>{patron})" for nombre, patron in ESPECIFICACION_TOKENS)
)


def tokenizar(codigo_fuente: str) -> List[Token]:
    """
    Escanea el código fuente en una sola pasada y produce la lista de tokens.

    - Ignora espacios y comentarios (etiquetados como SKIP), actualizando
      correctamente el contador de líneas incluso en comentarios multilínea /* ... */.
    - Registra todos los caracteres ilegales con su línea y columna sin detener
      prematuramente la inspección léxica, y lanza ErrorLexico al finalizar si hubo errores.
    """
    tokens: List[Token] = []
    errores_lexicos: List[str] = []

    num_linea = 1
    inicio_linea = 0

    for match in PATRON_MAESTRO.finditer(codigo_fuente):
        tipo = match.lastgroup
        lexema = match.group()
        columna = match.start() - inicio_linea + 1

        if tipo == "NEWLINE":
            num_linea += 1
            inicio_linea = match.end()
            continue

        if tipo in ("SKIP", "COMMENT_SINGLE"):
            continue

        if tipo == "COMMENT_MULTI":
            saltos = lexema.count("\n")
            if saltos > 0:
                num_linea += saltos
                ultimo_salto = lexema.rfind("\n")
                inicio_linea = match.start() + ultimo_salto + 1
            continue

        if tipo == "ERROR":
            errores_lexicos.append(
                f"Carácter ilegal {lexema!r} en L:{num_linea}, C:{columna}"
            )
            continue

        assert tipo is not None
        tokens.append(Token(tipo=tipo, valor=lexema, linea=num_linea, columna=columna))

    if errores_lexicos:
        raise ErrorLexico(errores_lexicos)

    return tokens
