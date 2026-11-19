"""
Fase 2.2 (Middle-End): Optimización de Código Intermedio (IR / Cuádruplas TAC).

Implementa `OptimizadorTAC` y la función auxiliar `optimizar_cuadruplas`, ejecutando
pasadas de optimización independientes de la máquina sobre la lista de cuádruplas:
1. **Plegado de Constantes (Constant Folding)**:
   Evalúa en tiempo de compilación las operaciones binarias (`+`, `-`, `*`, `/`) cuyos
   dos operandos son constantes literales conocidas (`100 + 25 * 2 -> 150`).
2. **Propagación de Constantes en Temporales (Temporary Constant Propagation)**:
   Sustituye las referencias a temporales (`t1, t2, ...`) cuyo valor ya fue plegado a una
   constante por dicho valor literal en las instrucciones subsecuentes, preservando intactas
   las referencias a variables de usuario (`a, b, c, d, canal_base`) para que las expresiones
   con variables ejerciten el asignador de registros físicos (`R0, R1, R2`) en el Back-End.
3. **Eliminación de Código/Temporales Muertos (Dead Temporary Elimination)**:
   Elimina aquellas cuádruplas que definen temporales (`t_k`) que jamás vuelven a ser
   referenciados como operando en ninguna instrucción posterior.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Set, Tuple
from .ir_tac import Cuadrupla


@dataclass
class ReporteOptimizacion:
    """Contiene las cuádruplas optimizadas y las métricas de reducción obtenidas."""

    cuadruplas_originales: List[Cuadrupla]
    cuadruplas_optimizadas: List[Cuadrupla]
    bitacora_transformaciones: List[str]

    @property
    def total_antes(self) -> int:
        return len(self.cuadruplas_originales)

    @property
    def total_despues(self) -> int:
        return len(self.cuadruplas_optimizadas)

    @property
    def porcentaje_reduccion(self) -> float:
        if self.total_antes == 0:
            return 0.0
        eliminadas = self.total_antes - self.total_despues
        return (eliminadas / self.total_antes) * 100.0


class OptimizadorTAC:
    """
    Optimizador de representación intermedia TAC mediante plegado de constantes,
    propagación de temporales constantes y eliminación de temporales muertos.
    """

    @staticmethod
    def _es_temporal(identificador: Any) -> bool:
        return (
            isinstance(identificador, str)
            and len(identificador) >= 2
            and identificador[0] == "t"
            and identificador[1:].isdigit()
        )

    @staticmethod
    def _es_constante_numerica(valor: Any) -> bool:
        return isinstance(valor, (int, float)) and not isinstance(valor, bool)

    @staticmethod
    def _es_constante_literal(valor: Any) -> bool:
        if OptimizadorTAC._es_constante_numerica(valor):
            return True
        if (
            isinstance(valor, str)
            and len(valor) >= 2
            and valor.startswith('"')
            and valor.endswith('"')
        ):
            return True
        return False

    def optimizar(self, cuadruplas: List[Cuadrupla]) -> ReporteOptimizacion:
        """
        Aplica pasadas sucesivas de plegado/propagación de constantes y eliminación
        de temporales muertos hasta alcanzar un punto fijo.
        """
        originales = [
            Cuadrupla(c.op, c.arg1, c.arg2, c.resultado) for c in cuadruplas
        ]
        actuales = [
            Cuadrupla(c.op, c.arg1, c.arg2, c.resultado) for c in cuadruplas
        ]
        bitacora: List[str] = []

        # Pasada 1: Plegado y propagación de constantes sobre temporales
        actuales, logs_plegado = self._plegar_y_propagar_constantes(actuales)
        bitacora.extend(logs_plegado)

        # Pasada 2: Eliminación iterativa de temporales muertos hasta punto fijo
        iteracion = 1
        while True:
            nuevas, logs_dce = self._eliminar_temporales_muertos(actuales, iteracion)
            if not logs_dce:
                break
            bitacora.extend(logs_dce)
            actuales = nuevas
            iteracion += 1

        return ReporteOptimizacion(
            cuadruplas_originales=originales,
            cuadruplas_optimizadas=actuales,
            bitacora_transformaciones=bitacora,
        )

    def _plegar_y_propagar_constantes(
        self, cuadruplas: List[Cuadrupla]
    ) -> Tuple[List[Cuadrupla], List[str]]:
        """
        Evalúa operaciones entre literales constantes y propaga los temporales plegados.
        Las variables con nombre de usuario se conservan como accesos a variables para
        respetar su almacenamiento en Stack Frames y su carga en registros físicos.
        """
        temporales_constantes: Dict[str, Any] = {}
        resultado: List[Cuadrupla] = []
        logs: List[str] = []

        for idx, cuad in enumerate(cuadruplas):
            op = cuad.op
            arg1 = cuad.arg1
            arg2 = cuad.arg2
            dest = cuad.resultado

            if isinstance(arg1, str) and arg1 in temporales_constantes:
                nuevo_a1 = temporales_constantes[arg1]
                logs.append(
                    f"[Propagación] Cuádrupla #{idx}: temporal '{arg1}' sustituido por constante {nuevo_a1!r}"
                )
                arg1 = nuevo_a1

            if isinstance(arg2, str) and arg2 in temporales_constantes:
                nuevo_a2 = temporales_constantes[arg2]
                logs.append(
                    f"[Propagación] Cuádrupla #{idx}: temporal '{arg2}' sustituido por constante {nuevo_a2!r}"
                )
                arg2 = nuevo_a2

            if (
                op in ("CANAL", "ESPERA", "MEZCLA")
                and isinstance(dest, str)
                and dest in temporales_constantes
            ):
                nuevo_d = str(temporales_constantes[dest])
                logs.append(
                    f"[Propagación] Cuádrupla #{idx}: temporal '{dest}' sustituido por constante {nuevo_d}"
                )
                dest = nuevo_d

            if (
                op in ("+", "-", "*", "/")
                and self._es_constante_numerica(arg1)
                and self._es_constante_numerica(arg2)
            ):
                if op == "/" and arg2 == 0:
                    resultado.append(Cuadrupla(op, arg1, arg2, dest))
                    temporales_constantes.pop(dest, None)
                    continue

                if op == "+":
                    val_plegado = arg1 + arg2
                elif op == "-":
                    val_plegado = arg1 - arg2
                elif op == "*":
                    val_plegado = arg1 * arg2
                else:
                    if (
                        isinstance(arg1, int)
                        and isinstance(arg2, int)
                        and arg1 % arg2 == 0
                    ):
                        val_plegado = arg1 // arg2
                    else:
                        val_plegado = arg1 / arg2

                logs.append(
                    f"[Plegado    ] Cuádrupla #{idx}: '{dest} = {arg1} {op} {arg2}' -> plegado a '{dest} = {val_plegado}'"
                )
                if self._es_temporal(dest):
                    temporales_constantes[dest] = val_plegado
                resultado.append(Cuadrupla("=", val_plegado, None, dest))
                continue

            if op == "=" and self._es_constante_literal(arg1) and self._es_temporal(dest):
                temporales_constantes[dest] = arg1
                resultado.append(Cuadrupla(op, arg1, arg2, dest))
                continue

            temporales_constantes.pop(dest, None)
            resultado.append(Cuadrupla(op, arg1, arg2, dest))

        return resultado, logs

    def _eliminar_temporales_muertos(
        self, cuadruplas: List[Cuadrupla], iteracion: int
    ) -> Tuple[List[Cuadrupla], List[str]]:
        """
        Identifica todos los temporales leídos en `arg1` o `arg2` y elimina las cuádruplas
        cuyo destino sea un temporal que no tiene ninguna lectura posterior.
        """
        temporales_usados: Set[str] = set()
        for cuad in cuadruplas:
            if self._es_temporal(cuad.arg1):
                temporales_usados.add(cuad.arg1)
            if self._es_temporal(cuad.arg2):
                temporales_usados.add(cuad.arg2)
            if cuad.op in ("CANAL", "ESPERA", "MEZCLA") and self._es_temporal(cuad.resultado):
                temporales_usados.add(cuad.resultado)

        conservadas: List[Cuadrupla] = []
        logs: List[str] = []

        for idx, cuad in enumerate(cuadruplas):
            if (
                cuad.op not in ("CANAL", "ESPERA", "MEZCLA")
                and self._es_temporal(cuad.resultado)
                and cuad.resultado not in temporales_usados
            ):
                logs.append(
                    f"[Temp Muerto] Pasada #{iteracion}: eliminada cuádrupla #{idx} "
                    f"({cuad.formatear_tac()}) porque '{cuad.resultado}' no se referencia posteriormente."
                )
                continue
            conservadas.append(cuad)

        return conservadas, logs


def optimizar_cuadruplas(cuadruplas: List[Cuadrupla]) -> ReporteOptimizacion:
    """Función de alto nivel para optimizar una secuencia de cuádruplas TAC."""
    return OptimizadorTAC().optimizar(cuadruplas)
