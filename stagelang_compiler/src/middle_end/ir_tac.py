"""
Fase 2.1 (Middle-End): Representación Intermedia (TAC / Cuádruplas) y Emulador Virtual Integrado con Memoria.

Implementa:
- `Cuadrupla`: Tupla estructurada `(op, arg1, arg2, resultado)`.
- `GeneradorTAC`: Linealiza el AST generando variables temporales `t1, t2, ...` en post-orden,
  respetando precedencia de operadores y agrupación por paréntesis.
- `EmuladorVirtualIR`: Máquina virtual que ejecuta las cuádruplas directamente sobre
  `GestorMemoria` (Stack Frames LIFO y Heap Dinámico):
  1. Al iniciar la ejecución de la IR, abre el Stack Frame principal `push_stack_frame("GLOBAL")`.
  2. En `ESCENA_INICIO <nombre>`, apila un nuevo marco `push_stack_frame(f"escena_{nombre}")`,
     reserva un buffer de escena en el Heap (`reservar_heap`) guardando su puntero `0x1000+`
     en el Stack Frame actual, y aloja las variables locales de la escena en la cima del Stack.
  3. En comandos `MEZCLA`, reserva memoria dinámica en el Heap para el buffer de mezcla de efectos,
     almacenando el puntero hexadecimal (`0x1000+`) en el Stack Frame activo.
  4. En `ESCENA_FIN <nombre>`, libera los bloques de Heap asociados a la escena (`liberar_heap`)
     y desapila el marco (`pop_stack_frame()`), demostrando la destrucción LIFO de variables locales.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple
from ..frontend.parser import (
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
from ..frontend.semantico import SymbolTable
from ..backend.memoria import GestorMemoria


class ErrorEjecucionIR(Exception):
    """Excepción controlada lanzada por el Emulador Virtual IR en tiempo de ejecución."""


@dataclass
class Cuadrupla:
    """
    Representa una instrucción de Código de Tres Direcciones (TAC) en formato de cuádrupla:
        (op, arg1, arg2, resultado)
    """

    op: str
    arg1: Any
    arg2: Any
    resultado: str

    def como_tupla(self) -> Tuple[str, Any, Any, str]:
        """Devuelve la representación en tupla estándar de 4 elementos."""
        return (self.op, self.arg1, self.arg2, self.resultado)

    def formatear_tac(self) -> str:
        """Devuelve la instrucción en sintaxis legible de Código de Tres Direcciones."""
        if self.op in ("+", "-", "*", "/"):
            return f"{self.resultado} = {self.arg1} {self.op} {self.arg2}"
        if self.op == "=":
            return f"{self.resultado} = {self.arg1}"
        if self.op == "ESCENA_INICIO":
            return f"ESCENA_INICIO {self.resultado}"
        if self.op == "ESCENA_FIN":
            return f"ESCENA_FIN {self.resultado}"
        if self.op in ("CANAL", "ESPERA", "MEZCLA"):
            partes = [str(self.arg1)]
            if self.arg2 is not None:
                partes.append(str(self.arg2))
            if self.resultado not in ("-", "", None):
                partes.append(str(self.resultado))
            return f"{self.op} {', '.join(partes)}"
        return f"{self.op} {self.arg1}, {self.arg2} -> {self.resultado}"


class GeneradorTAC:
    """
    Traduce un AST validado a una lista lineal de cuádruplas TAC,
    asignando temporales únicos `t1, t2, ...` para cada subexpresión intermedia.
    """

    def __init__(self) -> None:
        self.cuadruplas: List[Cuadrupla] = []
        self.contador_temporales: int = 0

    def nuevo_temporal(self) -> str:
        """Genera un nuevo nombre de variable temporal (t1, t2, ...)."""
        self.contador_temporales += 1
        return f"t{self.contador_temporales}"

    def generar(self, nodo_raiz: ProgramaNode) -> List[Cuadrupla]:
        """Recorre el ProgramaNode y devuelve la secuencia de cuádruplas generadas."""
        self.cuadruplas.clear()
        self.contador_temporales = 0
        for sentencia in nodo_raiz.sentencias:
            self._generar_sentencia(sentencia)
        return list(self.cuadruplas)

    def _generar_sentencia(self, nodo: ASTNode) -> None:
        if isinstance(nodo, DeclaracionNode):
            origen = self._generar_expresion(nodo.expresion)
            self.cuadruplas.append(
                Cuadrupla(op="=", arg1=origen, arg2=None, resultado=nodo.nombre)
            )
            return

        if isinstance(nodo, AsignacionNode):
            origen = self._generar_expresion(nodo.expresion)
            self.cuadruplas.append(
                Cuadrupla(op="=", arg1=origen, arg2=None, resultado=nodo.nombre)
            )
            return

        if isinstance(nodo, ComandoEscenaNode):
            arg1_tac = self._generar_expresion(nodo.expresion)
            extras_tac = [self._generar_expresion(arg) for arg in nodo.argumentos_extra]
            arg2_tac = extras_tac[0] if len(extras_tac) >= 1 else None
            res_tac = str(extras_tac[1]) if len(extras_tac) >= 2 else "-"
            self.cuadruplas.append(
                Cuadrupla(
                    op=nodo.comando.upper(),
                    arg1=arg1_tac,
                    arg2=arg2_tac,
                    resultado=res_tac,
                )
            )
            return

        if isinstance(nodo, EscenaNode):
            self.cuadruplas.append(
                Cuadrupla(op="ESCENA_INICIO", arg1=None, arg2=None, resultado=nodo.nombre)
            )
            for sent in nodo.sentencias:
                self._generar_sentencia(sent)
            self.cuadruplas.append(
                Cuadrupla(op="ESCENA_FIN", arg1=None, arg2=None, resultado=nodo.nombre)
            )
            return

        raise TypeError(f"Sentencia no soportada en GeneradorTAC: {type(nodo).__name__}")

    def _generar_expresion(self, expr: ASTNode) -> Any:
        """
        Evalúa la expresión en post-orden para emitir primero las cuádruplas de los operandos
        hijos y retorna el identificador o literal resultante.
        """
        if isinstance(expr, NumberNode):
            return expr.valor

        if isinstance(expr, StringNode):
            return f'"{expr.valor}"'

        if isinstance(expr, VarNode):
            return expr.nombre

        if isinstance(expr, BinOpNode):
            arg_izq = self._generar_expresion(expr.izquierda)
            arg_der = self._generar_expresion(expr.derecha)
            temp = self.nuevo_temporal()
            self.cuadruplas.append(
                Cuadrupla(
                    op=expr.operador,
                    arg1=arg_izq,
                    arg2=arg_der,
                    resultado=temp,
                )
            )
            return temp

        raise TypeError(f"Expresión no soportada en GeneradorTAC: {type(expr).__name__}")


def formatear_tabla_cuadruplas(cuadruplas: List[Cuadrupla]) -> str:
    """Devuelve una tabla alineada con el índice, la cuádrupla y la instrucción TAC."""
    lineas = [
        f"{'ÍNDICE':<6} | {'OP':<14} | {'ARG1':<18} | {'ARG2':<18} | {'RESULTADO':<16} | {'INSTRUCCIÓN TAC'}"
    ]
    lineas.append("-" * 108)
    for idx, c in enumerate(cuadruplas):
        a1 = "-" if c.arg1 is None else str(c.arg1)
        a2 = "-" if c.arg2 is None else str(c.arg2)
        lineas.append(
            f"{idx:<6} | {c.op:<14} | {a1:<18} | {a2:<18} | {c.resultado:<16} | {c.formatear_tac()}"
        )
    return "\n".join(lineas)


class EmuladorVirtualIR:
    """
    Emulador virtual de Representación Intermedia integrado con `GestorMemoria`.

    - Las variables del programa se almacenan y consultan directamente en los Stack Frames
      de `GestorMemoria` (`GLOBAL` y `escena_<nombre>`), respetando el ciclo de vida LIFO.
    - Los registros temporales de evaluación (`t1, t2, ...`) residen en el banco temporal
      de la unidad de ejecución IR.
    - Los buffers de escena y efectos `MEZCLA` se reservan dinámicamente en el Heap (`0x1000+`),
      almacenando su puntero hexadecimal en el Stack Frame actual y liberándose al cerrar la escena.
    """

    def __init__(self, gestor_memoria: Optional[GestorMemoria] = None) -> None:
        self.gestor_memoria = gestor_memoria if gestor_memoria is not None else GestorMemoria()
        self.temporales_ir: Dict[str, Any] = {}
        self.eventos_escena: List[str] = []
        self.contador_mezclas: int = 0

    @staticmethod
    def _es_temporal(identificador: Any) -> bool:
        return (
            isinstance(identificador, str)
            and len(identificador) >= 2
            and identificador[0] == "t"
            and identificador[1:].isdigit()
        )

    @staticmethod
    def _extraer_locales_por_ambito(
        tabla_simbolos: Optional[SymbolTable],
    ) -> Dict[str, Set[str]]:
        """
        Extrae de la `SymbolTable` qué variables fueron declaradas localmente en cada ámbito
        (`GLOBAL`, `escena_apertura`, etc.) para alojarlas en el Stack Frame correspondiente.
        """
        mapa: Dict[str, Set[str]] = {}
        if tabla_simbolos is None:
            return mapa
        for scope in tabla_simbolos.historial_ambitos:
            mapa[scope.nombre] = set(scope.simbolos.keys())
        return mapa

    def _resolver_operando(self, operando: Any) -> Any:
        """
        Obtiene el valor de un operando:
        1. Constante numérica o literal de cadena.
        2. Variable temporal (`t1, t2, ...`) del banco temporal IR.
        3. Variable del programa alojada en la pila de Stack Frames (`GestorMemoria`).
        """
        if isinstance(operando, (int, float)):
            return operando
        if isinstance(operando, str):
            if len(operando) >= 2 and operando.startswith('"') and operando.endswith('"'):
                return operando[1:-1]
            try:
                if "." in operando:
                    return float(operando)
                return int(operando)
            except ValueError:
                pass

            if self._es_temporal(operando):
                if operando in self.temporales_ir:
                    return self.temporales_ir[operando]
                raise ErrorEjecucionIR(
                    f"Temporal '{operando}' no inicializado en el Emulador Virtual IR."
                )

            try:
                return self.gestor_memoria.obtener_valor(operando)
            except KeyError as exc:
                raise ErrorEjecucionIR(
                    f"Variable '{operando}' no encontrada en los Stack Frames activos: {exc}"
                ) from exc

        return operando

    def ejecutar(
        self,
        cuadruplas: List[Cuadrupla],
        gestor_memoria: Optional[GestorMemoria] = None,
        tabla_simbolos: Optional[SymbolTable] = None,
    ) -> Dict[str, Any]:
        """
        Ejecuta paso a paso las cuádruplas TAC operando directamente sobre `GestorMemoria`.
        """
        if gestor_memoria is not None:
            self.gestor_memoria = gestor_memoria

        self.temporales_ir.clear()
        self.eventos_escena.clear()
        self.contador_mezclas = 0

        locales_por_ambito = self._extraer_locales_por_ambito(tabla_simbolos)

        # 1. Al iniciar la ejecución de la IR, aseguramos que exista el Stack Frame principal "GLOBAL"
        if not self.gestor_memoria.pila_frames:
            self.gestor_memoria.push_stack_frame("GLOBAL")

        for idx, cuad in enumerate(cuadruplas):
            op = cuad.op

            # -------------------------------------------------------------
            # Entrada a Escena: PUSH Stack Frame + Reserva de Buffer en Heap
            # -------------------------------------------------------------
            if op == "ESCENA_INICIO":
                nombre_escena = cuad.resultado
                nombre_frame = f"escena_{nombre_escena}"
                frame = self.gestor_memoria.push_stack_frame(nombre_frame)

                # Reservamos un buffer de contexto DMX para la escena en el Heap dinámico
                ptr_buffer = self.gestor_memoria.reservar_heap(
                    etiqueta=f"Buffer_Escena_{nombre_escena}",
                    datos={"escena": nombre_escena, "estado": "ACTIVA"},
                    tamano_bytes=64,
                )
                dir_slot_ptr = self.gestor_memoria.registrar_puntero_en_frame_actual(
                    f"__heap_ptr_{nombre_escena}", ptr_buffer
                )
                self.eventos_escena.append(
                    f"-> [ESCENA_INICIO {nombre_escena}] Stack Frame '{nombre_frame}' abierto en "
                    f"FP={frame.base_hex} | Buffer Heap={ptr_buffer} (guardado en Stack {dir_slot_ptr})"
                )
                continue

            # -------------------------------------------------------------
            # Salida de Escena: Liberación de Heap + POP Stack Frame (LIFO)
            # -------------------------------------------------------------
            if op == "ESCENA_FIN":
                nombre_escena = cuad.resultado
                frame_actual = self.gestor_memoria.frame_actual
                punteros_a_liberar = (
                    list(frame_actual.punteros_heap_asociados)
                    if frame_actual is not None
                    else []
                )
                for ptr in punteros_a_liberar:
                    self.gestor_memoria.liberar_heap(ptr)

                frame_cerrado = self.gestor_memoria.pop_stack_frame()
                vars_destruidas = list(frame_cerrado.variables.keys())
                self.eventos_escena.append(
                    f"<- [ESCENA_FIN {nombre_escena}] Liberados bloques Heap {punteros_a_liberar} | "
                    f"Stack Frame '{frame_cerrado.nombre_contexto}' (FP={frame_cerrado.base_hex}) "
                    f"destruido (variables locales eliminadas: {vars_destruidas})"
                )
                continue

            # -------------------------------------------------------------
            # Asignación a Temporal o Variable en Stack Frame
            # -------------------------------------------------------------
            if op == "=":
                valor = self._resolver_operando(cuad.arg1)
                destino = cuad.resultado
                if self._es_temporal(destino):
                    self.temporales_ir[destino] = valor
                else:
                    frame_tope = self.gestor_memoria.frame_actual
                    nombre_ambito_actual = (
                        frame_tope.nombre_contexto if frame_tope else "GLOBAL"
                    )
                    es_local_declarada = destino in locales_por_ambito.get(
                        nombre_ambito_actual, set()
                    )
                    self.gestor_memoria.asignar_local(
                        destino,
                        valor,
                        forzar_marco_actual=es_local_declarada,
                    )
                continue

            # -------------------------------------------------------------
            # Operaciones Aritméticas Binarias (+, -, *, /)
            # -------------------------------------------------------------
            if op in ("+", "-", "*", "/"):
                val_izq = self._resolver_operando(cuad.arg1)
                val_der = self._resolver_operando(cuad.arg2)

                if op == "+":
                    res = val_izq + val_der
                elif op == "-":
                    res = val_izq - val_der
                elif op == "*":
                    res = val_izq * val_der
                else:
                    if val_der == 0:
                        raise ErrorEjecucionIR(
                            f"División por cero detectada en cuádrupla #{idx}: "
                            f"({cuad.formatear_tac()})"
                        )
                    if (
                        isinstance(val_izq, int)
                        and isinstance(val_der, int)
                        and val_izq % val_der == 0
                    ):
                        res = val_izq // val_der
                    else:
                        res = val_izq / val_der

                if self._es_temporal(cuad.resultado):
                    self.temporales_ir[cuad.resultado] = res
                else:
                    self.gestor_memoria.asignar_local(cuad.resultado, res)
                continue

            # -------------------------------------------------------------
            # Comandos de Escena: CANAL, ESPERA y MEZCLA (con Heap)
            # -------------------------------------------------------------
            if op in ("CANAL", "ESPERA", "MEZCLA"):
                val1 = self._resolver_operando(cuad.arg1)
                val2 = (
                    self._resolver_operando(cuad.arg2)
                    if cuad.arg2 is not None
                    else None
                )
                val3 = (
                    self._resolver_operando(cuad.resultado)
                    if cuad.resultado not in ("-", "", None)
                    else None
                )

                if op == "MEZCLA":
                    self.contador_mezclas += 1
                    datos_heap = (
                        {"canal_a": val1, "canal_b": val2, "resultado": val3}
                        if val2 is not None
                        else {"preset": val1, "canales_activos": 8}
                    )
                    ptr_mezcla = self.gestor_memoria.reservar_heap(
                        etiqueta=f"Preset_Mezcla_{self.contador_mezclas}",
                        datos=datos_heap,
                        tamano_bytes=64,
                    )
                    dir_ptr_stack = self.gestor_memoria.registrar_puntero_en_frame_actual(
                        f"__ptr_mezcla_{self.contador_mezclas}", ptr_mezcla
                    )
                    self.eventos_escena.append(
                        f"   [CMD MEZCLA] Datos={datos_heap!r} -> reservado en Heap {ptr_mezcla} "
                        f"(puntero alojado en Stack {dir_ptr_stack})"
                    )
                elif op == "CANAL" and val2 is not None:
                    self.eventos_escena.append(
                        f"   [CMD CANAL ] Canal={val1!r}, Intensidad={val2!r}"
                    )
                else:
                    self.eventos_escena.append(
                        f"   [CMD {op:<6}] Ejecutado con valor={val1!r}"
                    )
                continue

            raise ErrorEjecucionIR(f"Código de operación IR desconocido: '{op}'")

        # Construimos el snapshot de variables visibles en el marco GLOBAL al finalizar
        variables_globales: Dict[str, Any] = {}
        if self.gestor_memoria.pila_frames:
            for nombre, slot in self.gestor_memoria.pila_frames[0].variables.items():
                variables_globales[nombre] = slot.valor
        return variables_globales
