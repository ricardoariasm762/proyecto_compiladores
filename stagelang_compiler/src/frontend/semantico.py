"""
Fase 1.3 (Front-End): Tabla de Símbolos, Gestión Jerárquica de Ámbitos (Scopes) y Chequeo de Tipos.

Implementa:
- `Symbol`: Metadatos de cada identificador declarado (nombre, tipo, ámbito, línea, valor).
- `Scope`: Diccionario local de símbolos con puntero al ámbito padre (`GLOBAL -> escena_*`).
- `SymbolTable`: Pila de ámbitos activos con `entrar_ambito()`, `salir_ambito()`,
  `declarar()` y `buscar()` jerárquico.
- `AnalizadorSemantico`: Recorre el AST validando unicidad de declaraciones, visibilidad
  de variables por ámbito e inferencia/compatibilidad de tipos (INT, FLOAT, STR) con
  coerción implícita segura de INT -> FLOAT.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from .parser import (
    ASTNode,
    AsignacionNode,
    BinOpNode,
    ComandoEscenaNode,
    DeclaracionNode,
    EscenaNode,
    NumberNode,
    ProgramaNode,
    StringNode,
    VarNode,
)


class ErrorSemantico(Exception):
    """Excepción controlada lanzada ante violaciones de ámbito o incompatibilidad de tipos."""

    def __init__(self, mensaje: str, linea: int = 0, columna: int = 0) -> None:
        self.linea = linea
        self.columna = columna
        ubicacion = f" (L:{linea}, C:{columna})" if linea > 0 else ""
        super().__init__(f"Error semántico{ubicacion}: {mensaje}")


@dataclass
class Symbol:
    """Representa una entrada en la Tabla de Símbolos."""

    nombre: str
    tipo: str  # 'INT', 'FLOAT', 'STR'
    ambito: str
    linea_declaracion: int
    valor_inicial: Any = None


@dataclass
class Scope:
    """
    Representa un ámbito léxico (ej. 'GLOBAL' o 'escena_intro') con enlace a su ámbito padre
    para permitir resolución jerárquica de nombres.
    """

    nombre: str
    padre: Optional["Scope"] = None
    simbolos: Dict[str, Symbol] = field(default_factory=dict)

    def declarar_local(self, simbolo: Symbol) -> None:
        """Registra un símbolo en el ámbito actual; bloquea redeclaraciones duplicadas."""
        if simbolo.nombre in self.simbolos:
            existente = self.simbolos[simbolo.nombre]
            raise ErrorSemantico(
                f"Redeclaración duplicada de la variable '{simbolo.nombre}' en el ámbito "
                f"'{self.nombre}' (declarada previamente en L:{existente.linea_declaracion}).",
                linea=simbolo.linea_declaracion,
            )
        self.simbolos[simbolo.nombre] = simbolo

    def buscar_jerarquico(self, nombre: str) -> Optional[Symbol]:
        """Busca un símbolo en el ámbito actual y, si no está, asciende hacia los padres."""
        if nombre in self.simbolos:
            return self.simbolos[nombre]
        if self.padre is not None:
            return self.padre.buscar_jerarquico(nombre)
        return None


class SymbolTable:
    """
    Administra la pila de ámbitos activos durante el análisis semántico y conserva
    un historial de todos los ámbitos creados para su inspección y reporte.
    """

    def __init__(self) -> None:
        self.ambito_global = Scope(nombre="GLOBAL", padre=None)
        self.pila_ambitos: List[Scope] = [self.ambito_global]
        self.historial_ambitos: List[Scope] = [self.ambito_global]

    @property
    def ambito_actual(self) -> Scope:
        """Retorna el ámbito que se encuentra en el tope de la pila."""
        return self.pila_ambitos[-1]

    def entrar_ambito(self, nombre_ambito: str) -> Scope:
        """Crea un nuevo ámbito hijo del ámbito actual y lo apila."""
        nuevo = Scope(nombre=nombre_ambito, padre=self.ambito_actual)
        self.pila_ambitos.append(nuevo)
        self.historial_ambitos.append(nuevo)
        return nuevo

    def salir_ambito(self) -> Scope:
        """Desapila el ámbito actual y retorna al ámbito padre."""
        if len(self.pila_ambitos) <= 1:
            raise RuntimeError("No se puede salir del ámbito GLOBAL raíz.")
        return self.pila_ambitos.pop()

    def declarar(
        self,
        nombre: str,
        tipo: str,
        linea: int,
        valor_inicial: Any = None,
    ) -> Symbol:
        """Declara un nuevo identificador dentro del ámbito actual."""
        simbolo = Symbol(
            nombre=nombre,
            tipo=tipo,
            ambito=self.ambito_actual.nombre,
            linea_declaracion=linea,
            valor_inicial=valor_inicial,
        )
        self.ambito_actual.declarar_local(simbolo)
        return simbolo

    def buscar(self, nombre: str) -> Optional[Symbol]:
        """Busca un identificador desde el ámbito actual hacia la raíz GLOBAL."""
        return self.ambito_actual.buscar_jerarquico(nombre)

    def resumen_tabla(self) -> str:
        """Formatea todos los símbolos registrados por ámbito para visualización en consola."""
        lineas = [
            f"{'IDENTIFICADOR':<18} | {'TIPO':<8} | {'ÁMBITO':<18} | {'PADRE':<12} | {'LÍNEA':<5}"
        ]
        lineas.append("-" * 72)
        for scope in self.historial_ambitos:
            nombre_padre = scope.padre.nombre if scope.padre else "-"
            for simb in scope.simbolos.values():
                lineas.append(
                    f"{simb.nombre:<18} | {simb.tipo:<8} | {simb.ambito:<18} | "
                    f"{nombre_padre:<12} | L:{simb.linea_declaracion}"
                )
        return "\n".join(lineas)


class AnalizadorSemantico:
    """
    Validador semántico que recorre el AST comprobando reglas de ámbito y sistema de tipos.
    """

    def __init__(self) -> None:
        self.tabla = SymbolTable()
        self.decisiones_tipos: List[str] = []

    def analizar(self, nodo_raiz: ProgramaNode) -> SymbolTable:
        """Ejecuta el análisis semántico sobre el programa completo."""
        for sentencia in nodo_raiz.sentencias:
            self._visitar_sentencia(sentencia)
        return self.tabla

    def _visitar_sentencia(self, nodo: ASTNode) -> None:
        if isinstance(nodo, DeclaracionNode):
            tipo_expr = self.inferir_tipo(nodo.expresion)
            self._validar_compatibilidad_asignacion(
                tipo_destino=nodo.tipo_variable,
                tipo_origen=tipo_expr,
                nombre_var=nodo.nombre,
                linea=nodo.linea,
                columna=nodo.columna,
            )
            self.tabla.declarar(
                nombre=nodo.nombre,
                tipo=nodo.tipo_variable,
                linea=nodo.linea,
            )
            self.decisiones_tipos.append(
                f"L:{nodo.linea:<2} Declaración '{nodo.nombre}' ({nodo.tipo_variable}) "
                f"<- expresión de tipo {tipo_expr} [OK]"
            )
            return

        if isinstance(nodo, AsignacionNode):
            simbolo = self.tabla.buscar(nodo.nombre)
            if simbolo is None:
                raise ErrorSemantico(
                    f"La variable '{nodo.nombre}' no ha sido declarada o está fuera de ámbito "
                    f"(ámbito actual: '{self.tabla.ambito_actual.nombre}').",
                    linea=nodo.linea,
                    columna=nodo.columna,
                )
            tipo_expr = self.inferir_tipo(nodo.expresion)
            self._validar_compatibilidad_asignacion(
                tipo_destino=simbolo.tipo,
                tipo_origen=tipo_expr,
                nombre_var=nodo.nombre,
                linea=nodo.linea,
                columna=nodo.columna,
            )
            self.decisiones_tipos.append(
                f"L:{nodo.linea:<2} Reasignación '{nodo.nombre}' ({simbolo.tipo}, ámbito {simbolo.ambito}) "
                f"<- expresión de tipo {tipo_expr} [OK]"
            )
            return

        if isinstance(nodo, ComandoEscenaNode):
            tipo_expr = self.inferir_tipo(nodo.expresion)
            tipos_extra = [self.inferir_tipo(arg) for arg in nodo.argumentos_extra]
            todos_tipos = [tipo_expr, *tipos_extra]

            if nodo.comando in ("canal", "espera"):
                for t_arg in todos_tipos:
                    if t_arg not in ("INT", "FLOAT"):
                        raise ErrorSemantico(
                            f"El comando '{nodo.comando}' requiere expresiones numéricas (INT o FLOAT), "
                            f"pero recibió '{t_arg}'.",
                            linea=nodo.linea,
                            columna=nodo.columna,
                        )
            elif nodo.comando == "mezcla" and tipos_extra:
                # Si mezcla se usa con múltiples argumentos (canal_a, canal_b [, resultado]), todos deben ser numéricos
                for t_arg in todos_tipos:
                    if t_arg not in ("INT", "FLOAT"):
                        raise ErrorSemantico(
                            f"El comando 'mezcla' multi-canal requiere expresiones numéricas (INT o FLOAT), "
                            f"pero recibió '{t_arg}'.",
                            linea=nodo.linea,
                            columna=nodo.columna,
                        )

            desc_tipos = ", ".join(todos_tipos)
            self.decisiones_tipos.append(
                f"L:{nodo.linea:<2} Comando '{nodo.comando}' con argumento(s) de tipo ({desc_tipos}) [OK]"
            )
            return

        if isinstance(nodo, EscenaNode):
            nombre_ambito = f"escena_{nodo.nombre}"
            self.tabla.entrar_ambito(nombre_ambito)
            try:
                for sent in nodo.sentencias:
                    self._visitar_sentencia(sent)
            finally:
                self.tabla.salir_ambito()
            return

        raise ErrorSemantico(
            f"Sentencia desconocida en análisis semántico: {type(nodo).__name__}",
            linea=nodo.linea,
            columna=nodo.columna,
        )

    def inferir_tipo(self, expr: ASTNode) -> str:
        """
        Infiere recursivamente el tipo de una expresión ('INT', 'FLOAT' o 'STR')
        y verifica que las operaciones sean válidas.
        """
        if isinstance(expr, NumberNode):
            return expr.tipo_dato

        if isinstance(expr, StringNode):
            return "STR"

        if isinstance(expr, VarNode):
            simbolo = self.tabla.buscar(expr.nombre)
            if simbolo is None:
                raise ErrorSemantico(
                    f"Uso de variable '{expr.nombre}' no declarada o fuera del ámbito "
                    f"'{self.tabla.ambito_actual.nombre}'.",
                    linea=expr.linea,
                    columna=expr.columna,
                )
            return simbolo.tipo

        if isinstance(expr, BinOpNode):
            tipo_izq = self.inferir_tipo(expr.izquierda)
            tipo_der = self.inferir_tipo(expr.derecha)

            if "STR" in (tipo_izq, tipo_der):
                if tipo_izq == "STR" and tipo_der == "STR" and expr.operador == "+":
                    return "STR"
                raise ErrorSemantico(
                    f"Operación '{expr.operador}' incompatible entre tipos '{tipo_izq}' y '{tipo_der}'. "
                    f"No se permite operar cadenas (STR) con números.",
                    linea=expr.linea,
                    columna=expr.columna,
                )

            if tipo_izq == "FLOAT" or tipo_der == "FLOAT":
                if tipo_izq != tipo_der:
                    self.decisiones_tipos.append(
                        f"L:{expr.linea:<2} Coerción implícita INT -> FLOAT en operación "
                        f"'{tipo_izq} {expr.operador} {tipo_der}' -> FLOAT"
                    )
                return "FLOAT"

            return "INT"

        raise ErrorSemantico(
            f"No se puede inferir tipo del nodo {type(expr).__name__}",
            linea=expr.linea,
            columna=expr.columna,
        )

    def _validar_compatibilidad_asignacion(
        self,
        tipo_destino: str,
        tipo_origen: str,
        nombre_var: str,
        linea: int,
        columna: int,
    ) -> None:
        if tipo_destino == tipo_origen:
            return
        if tipo_destino == "FLOAT" and tipo_origen == "INT":
            self.decisiones_tipos.append(
                f"L:{linea:<2} Coerción implícita segura INT -> FLOAT al asignar a '{nombre_var}'"
            )
            return
        raise ErrorSemantico(
            f"Incompatibilidad de tipos en '{nombre_var}': no se puede asignar un valor "
            f"de tipo '{tipo_origen}' a una variable de tipo '{tipo_destino}'.",
            linea=linea,
            columna=columna,
        )
