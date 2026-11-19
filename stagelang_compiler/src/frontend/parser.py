"""
Fase 1.2 (Front-End): Análisis Sintáctico (Parser por Descensión Recursiva) y Construcción del AST.

Implementa una gramática libre de contexto (EBNF) no ambigua y sin recursión
izquierda para StageLang:
    programa    -> sentencia*
    sentencia   -> declaracion | asignacion | comando_escena | bloque_escena
    declaracion -> ('int' | 'float' | 'string') ID '=' expr ';'
    asignacion  -> ID '=' expr ';'
    comando     -> ('canal' | 'espera' | 'mezcla') expr ';'
    escena      -> 'escena' ID '{' sentencia* '}'
    expr        -> term (('+' | '-') term)*
    term        -> factor (('*' | '/') factor)*
    factor      -> INT | FLOAT | STRING_LITERAL | ID | '(' expr ')'

Incluye también un evaluador recursivo del AST en post-orden (Tree Walking Interpreter).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from .lexer import Token


class ErrorSintactico(Exception):
    """Excepción controlada lanzada cuando la secuencia de tokens viola la gramática."""

    def __init__(self, mensaje: str, linea: int = 0, columna: int = 0) -> None:
        self.linea = linea
        self.columna = columna
        ubicacion = f" (L:{linea}, C:{columna})" if linea > 0 else ""
        super().__init__(f"Error sintáctico{ubicacion}: {mensaje}")


# =====================================================================
# Definición de Nodos del Árbol de Sintaxis Abstracta (AST)
# =====================================================================


@dataclass
class ASTNode:
    """Clase base para todos los nodos del AST."""

    linea: int = 0
    columna: int = 0


@dataclass
class NumberNode(ASTNode):
    """Representa un literal numérico entero (INT) o de punto flotante (FLOAT)."""

    valor: Union[int, float] = 0
    tipo_dato: str = "INT"  # 'INT' o 'FLOAT'


@dataclass
class StringNode(ASTNode):
    """Representa un literal de texto entre comillas dobles (STRING_LITERAL)."""

    valor: str = ""
    tipo_dato: str = "STR"


@dataclass
class VarNode(ASTNode):
    """Representa la referencia al identificador de una variable en una expresión."""

    nombre: str = ""


@dataclass
class BinOpNode(ASTNode):
    """Representa una operación binaria aritmética, relacional o lógica."""

    izquierda: ASTNode = field(default_factory=ASTNode)
    operador: str = ""
    derecha: ASTNode = field(default_factory=ASTNode)


@dataclass
class DeclaracionNode(ASTNode):
    """Representa la declaración tipada de una variable: tipo ID = expr;"""

    tipo_variable: str = ""  # 'INT', 'FLOAT' o 'STR'
    nombre: str = ""
    expresion: ASTNode = field(default_factory=ASTNode)


@dataclass
class AsignacionNode(ASTNode):
    """Representa la reasignación de una variable existente: ID = expr;"""

    nombre: str = ""
    expresion: ASTNode = field(default_factory=ASTNode)


@dataclass
class ComandoEscenaNode(ASTNode):
    """
    Representa un comando de control escénico:
    - Sintaxis de 1 argumento: (canal | espera | mezcla) expr ';'
    - Sintaxis multi-argumento:
        canal <expr_canal>, <expr_intensidad> ';'
        mezcla <expr_canal_a>, <expr_canal_b> [, <expr_resultado>] ';'
    """

    comando: str = ""  # 'canal', 'espera', 'mezcla'
    expresion: ASTNode = field(default_factory=ASTNode)
    argumentos_extra: List[ASTNode] = field(default_factory=list)


@dataclass
class EscenaNode(ASTNode):
    """Representa un bloque de escena con su propio ámbito local: escena ID { ... }"""

    nombre: str = ""
    sentencias: List[ASTNode] = field(default_factory=list)


@dataclass
class ProgramaNode(ASTNode):
    """Nodo raíz del AST que agrupa todas las sentencias y escenas del programa."""

    sentencias: List[ASTNode] = field(default_factory=list)


# =====================================================================
# Parser por Descensión Recursiva (Top-Down)
# =====================================================================


class Parser:
    """
    Analizador sintáctico descendente recursivo (LL(1)) para StageLang.
    Garantiza precedencia de operadores (*, / sobre +, -) y asociatividad izquierda.
    """

    MAPA_TIPOS = {
        "KW_INT": "INT",
        "KW_FLOAT": "FLOAT",
        "KW_STRING": "STR",
    }

    def __init__(self, tokens: List[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def token_actual(self) -> Optional[Token]:
        """Devuelve el token en la posición actual o None si se llegó al final (EOF)."""
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def consumir(self, tipo_esperado: Optional[str] = None) -> Token:
        """
        Verifica que el token actual coincida con `tipo_esperado`, avanza el cursor
        y retorna el token consumido. Si no coincide o hay fin de archivo inesperado,
        lanza ErrorSintactico con línea y columna exactas.
        """
        tok = self.token_actual()
        if tok is None:
            if self.tokens:
                ultimo = self.tokens[-1]
                linea, col = ultimo.linea, ultimo.columna + len(ultimo.valor)
            else:
                linea, col = 1, 1
            esperado_msg = f"Se esperaba '{tipo_esperado}'" if tipo_esperado else "Token"
            raise ErrorSintactico(
                f"Fin de entrada inesperado (EOF). {esperado_msg}.",
                linea=linea,
                columna=col,
            )

        if tipo_esperado is not None and tok.tipo != tipo_esperado:
            raise ErrorSintactico(
                f"Token inesperado {tok.valor!r} (tipo {tok.tipo}); se esperaba '{tipo_esperado}'.",
                linea=tok.linea,
                columna=tok.columna,
            )

        self.pos += 1
        return tok

    def parse(self) -> ProgramaNode:
        """Punto de entrada principal del parser: construye el ProgramaNode raíz."""
        sentencias: List[ASTNode] = []
        while self.token_actual() is not None:
            sentencias.append(self.parse_sentencia())
        return ProgramaNode(linea=1, columna=1, sentencias=sentencias)

    def parse_sentencia(self) -> ASTNode:
        """Determina y analiza el tipo de sentencia a partir del token de preanálisis (lookahead)."""
        tok = self.token_actual()
        assert tok is not None

        if tok.tipo in ("KW_INT", "KW_FLOAT", "KW_STRING"):
            return self.parse_declaracion()
        if tok.tipo == "KW_ESCENA":
            return self.parse_escena()
        if tok.tipo in ("KW_CANAL", "KW_ESPERA", "KW_MEZCLA"):
            return self.parse_comando_escena()
        if tok.tipo == "ID":
            return self.parse_asignacion()

        raise ErrorSintactico(
            f"Inicio de sentencia inválido con token {tok.valor!r} (tipo {tok.tipo}).",
            linea=tok.linea,
            columna=tok.columna,
        )

    def parse_declaracion(self) -> DeclaracionNode:
        """Analiza: ('int' | 'float' | 'string') ID '=' expr ';'"""
        tok_tipo = self.consumir()
        tipo_norm = self.MAPA_TIPOS[tok_tipo.tipo]
        tok_id = self.consumir("ID")
        self.consumir("ASSIGN")
        expr = self.parse_expr()
        self.consumir("SEMICOLON")
        return DeclaracionNode(
            linea=tok_tipo.linea,
            columna=tok_tipo.columna,
            tipo_variable=tipo_norm,
            nombre=tok_id.valor,
            expresion=expr,
        )

    def parse_asignacion(self) -> AsignacionNode:
        """Analiza: ID '=' expr ';'"""
        tok_id = self.consumir("ID")
        self.consumir("ASSIGN")
        expr = self.parse_expr()
        self.consumir("SEMICOLON")
        return AsignacionNode(
            linea=tok_id.linea,
            columna=tok_id.columna,
            nombre=tok_id.valor,
            expresion=expr,
        )

    def parse_comando_escena(self) -> ComandoEscenaNode:
        """
        Analiza comandos escénicos:
        - 1 argumento : ('canal' | 'espera' | 'mezcla') expr ';'
        - Multi-arg   : ('canal' | 'mezcla') expr (',' expr)+ ';'
        """
        tok_cmd = self.consumir()
        expr_principal = self.parse_expr()
        extras: List[ASTNode] = []
        while (tok := self.token_actual()) is not None and tok.tipo == "COMMA":
            self.consumir("COMMA")
            extras.append(self.parse_expr())
        self.consumir("SEMICOLON")
        return ComandoEscenaNode(
            linea=tok_cmd.linea,
            columna=tok_cmd.columna,
            comando=tok_cmd.valor,
            expresion=expr_principal,
            argumentos_extra=extras,
        )

    def parse_escena(self) -> EscenaNode:
        """Analiza: 'escena' ID '{' sentencia* '}'"""
        tok_esc = self.consumir("KW_ESCENA")
        tok_id = self.consumir("ID")
        self.consumir("LBRACE")

        sentencias: List[ASTNode] = []
        while True:
            tok = self.token_actual()
            if tok is None:
                raise ErrorSintactico(
                    f"Bloque de escena '{tok_id.valor}' sin cerrar; falta '}}'.",
                    linea=tok_esc.linea,
                    columna=tok_esc.columna,
                )
            if tok.tipo == "RBRACE":
                break
            sentencias.append(self.parse_sentencia())

        self.consumir("RBRACE")
        return EscenaNode(
            linea=tok_esc.linea,
            columna=tok_esc.columna,
            nombre=tok_id.valor,
            sentencias=sentencias,
        )

    def parse_expr(self) -> ASTNode:
        """
        Regla gramatical sin recursión izquierda:
            expr -> term (('+' | '-') term)*
        """
        nodo = self.parse_term()
        while (tok := self.token_actual()) is not None and tok.tipo in ("PLUS", "MINUS"):
            op_tok = self.consumir()
            derecho = self.parse_term()
            nodo = BinOpNode(
                linea=op_tok.linea,
                columna=op_tok.columna,
                izquierda=nodo,
                operador=op_tok.valor,
                derecha=derecho,
            )
        return nodo

    def parse_term(self) -> ASTNode:
        """
        Regla gramatical con mayor precedencia que expr:
            term -> factor (('*' | '/') factor)*
        """
        nodo = self.parse_factor()
        while (tok := self.token_actual()) is not None and tok.tipo in ("MUL", "DIV"):
            op_tok = self.consumir()
            derecho = self.parse_factor()
            nodo = BinOpNode(
                linea=op_tok.linea,
                columna=op_tok.columna,
                izquierda=nodo,
                operador=op_tok.valor,
                derecha=derecho,
            )
        return nodo

    def parse_factor(self) -> ASTNode:
        """
        Regla gramatical de máxima precedencia:
            factor -> INT | FLOAT | STRING_LITERAL | ID | '(' expr ')'
        """
        tok = self.token_actual()
        if tok is None:
            raise ErrorSintactico("Se esperaba una expresión, pero se alcanzó el final del archivo.")

        if tok.tipo == "INT":
            self.consumir("INT")
            return NumberNode(
                linea=tok.linea,
                columna=tok.columna,
                valor=int(tok.valor),
                tipo_dato="INT",
            )

        if tok.tipo == "FLOAT":
            self.consumir("FLOAT")
            return NumberNode(
                linea=tok.linea,
                columna=tok.columna,
                valor=float(tok.valor),
                tipo_dato="FLOAT",
            )

        if tok.tipo == "STRING_LITERAL":
            self.consumir("STRING_LITERAL")
            texto_limpio = tok.valor[1:-1]
            return StringNode(
                linea=tok.linea,
                columna=tok.columna,
                valor=texto_limpio,
                tipo_dato="STR",
            )

        if tok.tipo == "ID":
            self.consumir("ID")
            return VarNode(
                linea=tok.linea,
                columna=tok.columna,
                nombre=tok.valor,
            )

        if tok.tipo == "LPAREN":
            self.consumir("LPAREN")
            sub_expr = self.parse_expr()
            self.consumir("RPAREN")
            return sub_expr

        raise ErrorSintactico(
            f"Expresión inválida; token inesperado {tok.valor!r} (tipo {tok.tipo}).",
            linea=tok.linea,
            columna=tok.columna,
        )


# =====================================================================
# Evaluador Recursivo en Post-Orden (Tree Walking Interpreter) y Formato
# =====================================================================


def evaluar_ast(
    nodo: ASTNode,
    entorno: Optional[Dict[str, Any]] = None,
    log_salidas: Optional[List[str]] = None,
) -> Any:
    """
    Recorre y evalúa recursivamente el AST en post-orden (hijos primero, nodo padre después).
    """
    if entorno is None:
        entorno = {}
    if log_salidas is None:
        log_salidas = []

    if isinstance(nodo, ProgramaNode):
        for sentencia in nodo.sentencias:
            evaluar_ast(sentencia, entorno, log_salidas)
        return {"entorno": entorno, "traza": log_salidas}

    if isinstance(nodo, EscenaNode):
        entorno_escena = dict(entorno)
        log_salidas.append(f"[ESCENA INICIO] {nodo.nombre}")
        for sentencia in nodo.sentencias:
            evaluar_ast(sentencia, entorno_escena, log_salidas)
        for clave in entorno:
            if clave in entorno_escena:
                entorno[clave] = entorno_escena[clave]
        log_salidas.append(f"[ESCENA FIN] {nodo.nombre}")
        return None

    if isinstance(nodo, DeclaracionNode):
        valor = evaluar_ast(nodo.expresion, entorno, log_salidas)
        if nodo.tipo_variable == "FLOAT" and isinstance(valor, int):
            valor = float(valor)
        entorno[nodo.nombre] = valor
        log_salidas.append(f"[DECL] {nodo.tipo_variable} {nodo.nombre} = {valor!r}")
        return valor

    if isinstance(nodo, AsignacionNode):
        valor = evaluar_ast(nodo.expresion, entorno, log_salidas)
        entorno[nodo.nombre] = valor
        log_salidas.append(f"[ASIG] {nodo.nombre} = {valor!r}")
        return valor

    if isinstance(nodo, ComandoEscenaNode):
        valor = evaluar_ast(nodo.expresion, entorno, log_salidas)
        vals_extra = [evaluar_ast(arg, entorno, log_salidas) for arg in nodo.argumentos_extra]
        if vals_extra:
            todos = ", ".join(repr(v) for v in [valor, *vals_extra])
            log_salidas.append(f"[CMD {nodo.comando.upper()}] -> ({todos})")
        else:
            log_salidas.append(f"[CMD {nodo.comando.upper()}] -> {valor!r}")
        return valor

    if isinstance(nodo, NumberNode):
        return nodo.valor

    if isinstance(nodo, StringNode):
        return nodo.valor

    if isinstance(nodo, VarNode):
        return entorno[nodo.nombre]

    if isinstance(nodo, BinOpNode):
        izq = evaluar_ast(nodo.izquierda, entorno, log_salidas)
        der = evaluar_ast(nodo.derecha, entorno, log_salidas)
        if nodo.operador == "+":
            return izq + der
        if nodo.operador == "-":
            return izq - der
        if nodo.operador == "*":
            return izq * der
        if nodo.operador == "/":
            if der == 0:
                raise ZeroDivisionError(
                    f"División por cero al evaluar AST en L:{nodo.linea}, C:{nodo.columna}"
                )
            if isinstance(izq, int) and isinstance(der, int) and izq % der == 0:
                return izq // der
            return izq / der

    raise TypeError(f"Nodo AST no soportado en evaluación: {type(nodo).__name__}")


def formatear_ast(nodo: ASTNode, prefijo: str = "", es_ultimo: bool = True) -> str:
    """Genera una representación visual jerárquica en texto del AST."""
    conector = "└── " if es_ultimo else "├── "
    prefijo_hijo = prefijo + ("    " if es_ultimo else "│   ")

    if isinstance(nodo, ProgramaNode):
        lineas = ["ProgramaNode"]
        for i, sent in enumerate(nodo.sentencias):
            ult = i == len(nodo.sentencias) - 1
            lineas.append(formatear_ast(sent, "", ult))
        return "\n".join(lineas)

    if isinstance(nodo, EscenaNode):
        lineas = [f"{prefijo}{conector}EscenaNode(nombre={nodo.nombre!r})"]
        for i, sent in enumerate(nodo.sentencias):
            ult = i == len(nodo.sentencias) - 1
            lineas.append(formatear_ast(sent, prefijo_hijo, ult))
        return "\n".join(lineas)

    if isinstance(nodo, DeclaracionNode):
        cabecera = (
            f"{prefijo}{conector}DeclaracionNode(tipo={nodo.tipo_variable}, "
            f"nombre={nodo.nombre!r})"
        )
        hijo = formatear_ast(nodo.expresion, prefijo_hijo, True)
        return f"{cabecera}\n{hijo}"

    if isinstance(nodo, AsignacionNode):
        cabecera = f"{prefijo}{conector}AsignacionNode(nombre={nodo.nombre!r})"
        hijo = formatear_ast(nodo.expresion, prefijo_hijo, True)
        return f"{cabecera}\n{hijo}"

    if isinstance(nodo, ComandoEscenaNode):
        cabecera = f"{prefijo}{conector}ComandoEscenaNode(comando={nodo.comando!r})"
        todos_hijos = [nodo.expresion, *nodo.argumentos_extra]
        hijos_str = [
            formatear_ast(h, prefijo_hijo, idx == len(todos_hijos) - 1)
            for idx, h in enumerate(todos_hijos)
        ]
        return "\n".join([cabecera, *hijos_str])

    if isinstance(nodo, BinOpNode):
        cabecera = f"{prefijo}{conector}BinOpNode(op={nodo.operador!r})"
        izq = formatear_ast(nodo.izquierda, prefijo_hijo, False)
        der = formatear_ast(nodo.derecha, prefijo_hijo, True)
        return f"{cabecera}\n{izq}\n{der}"

    if isinstance(nodo, NumberNode):
        return f"{prefijo}{conector}NumberNode(valor={nodo.valor}, tipo={nodo.tipo_dato})"

    if isinstance(nodo, StringNode):
        return f"{prefijo}{conector}StringNode(valor={nodo.valor!r}, tipo={nodo.tipo_dato})"

    if isinstance(nodo, VarNode):
        return f"{prefijo}{conector}VarNode(nombre={nodo.nombre!r})"

    return f"{prefijo}{conector}{type(nodo).__name__}"
