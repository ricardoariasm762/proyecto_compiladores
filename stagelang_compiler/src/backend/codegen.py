"""
Fase 3.2 (Back-End): Generación de Código Objetivo, Análisis de Tiempo de Vida (Liveness) y Spill.

Implementa `GeneradorCodigoObjetivo`, el cual traduce las cuádruplas TAC a código ensamblador
de bajo nivel administrando un banco limitado de 3 registros físicos (`['R0', 'R1', 'R2']`):
1. **Análisis de Tiempo de Vida (*Liveness / Last-Use Analysis*)**:
   Antes de traducir las cuádruplas, calcula el índice exacto de la última cuádrupla en que se
   referencia cada variable temporal (`t1, t2, ...`) y cada símbolo del programa.
2. **Asignación y Liberación Automática de Registros Físicos (`R0, R1, R2`)**:
   - Si hay un registro libre en `['R0', 'R1', 'R2']`, lo asigna directamente.
   - Si `arg1` o `arg2` son temporales y la cuádrupla actual corresponde a su **último uso**
     (*last use*), libera automáticamente el registro físico que ocupaban para que pueda ser
     reutilizado por instrucciones posteriores sin desperdiciar registros.
3. **Mecanismo de Spill a Memoria de Stack (`0x2000+`)**:
   - Cuando los 3 registros físicos (`R0, R1, R2`) están simultáneamente ocupados por valores
     aún vivos, selecciona una víctima y ejecuta un **Spill** hacia el área de Stack (`0x2000+`),
     emitiendo `STORE [Rx], [0x2000+offset]` y recargándolo con `LOAD Ry, [0x2000+offset]`
     cuando vuelve a necesitarse.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from ..middle_end.ir_tac import Cuadrupla


@dataclass
class ResultadoCodegen:
    """Agrupa el código ensamblador emitido, la tabla de liveness, el mapa de spills y la traza."""

    instrucciones_asm: List[str] = field(default_factory=list)
    tabla_ultimo_uso: Dict[str, int] = field(default_factory=dict)
    mapa_spill: Dict[str, str] = field(default_factory=dict)
    eventos_registros: List[str] = field(default_factory=list)


class GeneradorCodigoObjetivo:
    """
    Traductor de cuádruplas TAC a código ensamblador de StageLang con análisis de
    tiempo de vida (*liveness*), reutilización de registros liberados y Spill a Stack (`0x2000+`).
    """

    MAPA_MNEMONICOS = {
        "+": "ADD",
        "-": "SUB",
        "*": "MUL",
        "/": "DIV",
    }

    def __init__(
        self,
        registros_fisicos: Optional[List[str]] = None,
        base_spill_hex: int = 0x2000,
    ) -> None:
        self.registros_fisicos: List[str] = (
            list(registros_fisicos) if registros_fisicos else ["R0", "R1", "R2"]
        )
        self.base_spill = base_spill_hex
        self.puntero_spill = base_spill_hex

        # Descriptor de registros: 'R0'..'R2' -> símbolo/temporal alojado o None si está libre
        self.descriptor_registros: Dict[str, Optional[str]] = {
            reg: None for reg in self.registros_fisicos
        }
        # Descriptor de ubicación: símbolo/temporal -> 'R0'..'R2' o '[0x2000+]'
        self.ubicacion_simbolo: Dict[str, str] = {}
        # Mapa histórico de símbolos/temporales que sufrieron Spill -> dirección '0x2000+'
        self.mapa_spill: Dict[str, str] = {}
        # Cola FIFO de uso para selección determinista de víctima en caso de Spill
        self.orden_asignacion: List[str] = []

        self.instrucciones_asm: List[str] = []
        self.eventos_registros: List[str] = []

    def _reiniciar_estado(self) -> None:
        self.puntero_spill = self.base_spill
        self.descriptor_registros = {reg: None for reg in self.registros_fisicos}
        self.ubicacion_simbolo.clear()
        self.mapa_spill.clear()
        self.orden_asignacion.clear()
        self.instrucciones_asm.clear()
        self.eventos_registros.clear()

    @staticmethod
    def _es_temporal(identificador: Any) -> bool:
        return (
            isinstance(identificador, str)
            and len(identificador) >= 2
            and identificador[0] == "t"
            and identificador[1:].isdigit()
        )

    @staticmethod
    def calcular_ultimo_uso(cuadruplas: List[Cuadrupla]) -> Dict[str, int]:
        """
        Recorre la secuencia TAC antes de traducir y calcula el último índice de uso
        (*last use*) de cada variable temporal (`t1, t2, ...`) y variable de usuario.
        """
        ultimo_uso: Dict[str, int] = {}
        for idx, cuad in enumerate(cuadruplas):
            operandos = [cuad.arg1, cuad.arg2]
            if cuad.op in ("CANAL", "ESPERA", "MEZCLA") and cuad.resultado not in ("-", "", None):
                operandos.append(cuad.resultado)
            for operando in operandos:
                if isinstance(operando, str) and not operando.startswith('"'):
                    ultimo_uso[operando] = idx
        return ultimo_uso

    def _vincular_registro(self, reg: str, simbolo: str) -> None:
        self.descriptor_registros[reg] = simbolo
        self.ubicacion_simbolo[simbolo] = reg
        if reg in self.orden_asignacion:
            self.orden_asignacion.remove(reg)
        self.orden_asignacion.append(reg)

    def _liberar_registro(self, reg: str, motivo: str) -> None:
        ocupante = self.descriptor_registros.get(reg)
        self.descriptor_registros[reg] = None
        if reg in self.orden_asignacion:
            self.orden_asignacion.remove(reg)
        if ocupante and self.ubicacion_simbolo.get(ocupante) == reg:
            self.ubicacion_simbolo.pop(ocupante, None)
        self.eventos_registros.append(f"[LIVENESS FREE ] {reg} liberado ({motivo})")

    def _seleccionar_victima(self, protegidos: Tuple[str, ...]) -> str:
        """
        Selecciona como víctima para Spill el registro ocupado más antiguo que no sea uno
        de los operandos activos de la instrucción actual (`protegidos`).
        Prioriza expulsar temporales cuyo próximo/último uso esté más lejano.
        """
        for reg in list(self.orden_asignacion):
            if reg not in protegidos:
                return reg
        for reg in self.registros_fisicos:
            if reg not in protegidos:
                return reg
        return self.registros_fisicos[0]

    def _adquirir_registro(
        self,
        simbolo_destino: str,
        indice_actual: int,
        ultimo_uso: Dict[str, int],
        protegidos: Tuple[str, ...] = (),
    ) -> str:
        """
        Adquiere un registro físico de `['R0', 'R1', 'R2']` para `simbolo_destino`:
        1. Si ya reside en un registro, lo retorna.
        2. Si existe un registro libre (`None`), lo asigna e informa si es reutilizado.
        3. Si hay un registro cuyo ocupante ya superó su `ultimo_uso`, lo libera por liveness y lo reutiliza.
        4. Si todos los registros físicos contienen valores aún vivos, ejecuta **Spill**
           hacia una dirección hexadecimal de Stack (`0x2000+`) emitiendo `STORE [Rx], [0x2000+offset]`.
        """
        ubic_actual = self.ubicacion_simbolo.get(simbolo_destino)
        if ubic_actual in self.descriptor_registros:
            return ubic_actual

        # 1. Buscar un registro libre en ['R0', 'R1', 'R2']
        for reg in self.registros_fisicos:
            if self.descriptor_registros[reg] is None:
                self._vincular_registro(reg, simbolo_destino)
                self.eventos_registros.append(
                    f"[REG ALLOC/REUSE] {reg} asignado a '{simbolo_destino}' "
                    f"(cuádrupla #{indice_actual}, último uso en #{ultimo_uso.get(simbolo_destino, indice_actual)})"
                )
                return reg

        # 2. Verificar si algún registro tiene un ocupante cuyo tiempo de vida ya expiró
        for reg in self.registros_fisicos:
            ocupante = self.descriptor_registros[reg]
            if (
                ocupante is not None
                and reg not in protegidos
                and ultimo_uso.get(ocupante, -1) < indice_actual
            ):
                self._liberar_registro(
                    reg,
                    f"fin de vida útil de '{ocupante}' antes de cuádrupla #{indice_actual}",
                )
                self._vincular_registro(reg, simbolo_destino)
                self.eventos_registros.append(
                    f"[REG REUSE     ] {reg} reutilizado inmediatamente para '{simbolo_destino}'"
                )
                return reg

        # 3. Todos los registros están ocupados por valores vivos -> SPILL a Stack (0x2000+)
        reg_victima = self._seleccionar_victima(protegidos)
        simbolo_victima = self.descriptor_registros[reg_victima]
        assert simbolo_victima is not None

        dir_spill = self.mapa_spill.get(simbolo_victima)
        if dir_spill is None:
            dir_spill = f"0x{self.puntero_spill:04X}"
            self.puntero_spill += 4
            self.mapa_spill[simbolo_victima] = dir_spill

        self.instrucciones_asm.append(
            f"    STORE   [{reg_victima}], [{dir_spill}]      ; SPILL de '{simbolo_victima}' al Stack (agotamiento de R0-R2)"
        )
        self.ubicacion_simbolo[simbolo_victima] = f"[{dir_spill}]"
        self.eventos_registros.append(
            f"[REG SPILL     ] Pool {self.registros_fisicos} saturado en cuádrupla #{indice_actual}: "
            f"'{simbolo_victima}' (vivo hasta #{ultimo_uso.get(simbolo_victima, '?')}) expulsado de "
            f"{reg_victima} -> [{dir_spill}] para alojar '{simbolo_destino}'"
        )

        self._vincular_registro(reg_victima, simbolo_destino)
        return reg_victima

    def _cargar_operando(
        self,
        operando: Any,
        indice_actual: int,
        ultimo_uso: Dict[str, int],
        protegidos: Tuple[str, ...] = (),
    ) -> str:
        """
        Garantiza que `operando` esté cargado en un registro físico (`R0..R2`).
        Si el operando había sido expulsado por Spill a `[0x2000+]`, emite `LOAD Rx, [0x2000+]`.
        """
        # Literal constante (número o string)
        if not isinstance(operando, str) or operando.startswith('"'):
            etiqueta_const = f"imm_{indice_actual}_{operando}"
            reg = self._adquirir_registro(
                etiqueta_const, indice_actual, ultimo_uso, protegidos
            )
            self.instrucciones_asm.append(f"    MOV     {reg}, {operando}")
            return reg

        # Si el temporal o variable ya está en un registro físico, lo usamos directamente
        ubic = self.ubicacion_simbolo.get(operando)
        if ubic in self.descriptor_registros:
            return ubic

        # Si el temporal o variable fue expulsado por Spill a [0x2000+], lo recargamos con LOAD
        reg = self._adquirir_registro(operando, indice_actual, ultimo_uso, protegidos)
        if ubic is not None and ubic.startswith("[0x"):
            self.instrucciones_asm.append(
                f"    LOAD    {reg}, {ubic}        ; RELOAD de '{operando}' desde dirección de Spill"
            )
            self.eventos_registros.append(
                f"[REG RELOAD    ] '{operando}' recargado desde {ubic} hacia {reg} en cuádrupla #{indice_actual}"
            )
        else:
            self.instrucciones_asm.append(f"    LOAD    {reg}, [{operando}]")
        return reg

    def _liberar_operando_si_ultimo_uso(
        self,
        operando: Any,
        reg_operando: Optional[str],
        indice_actual: int,
        ultimo_uso: Dict[str, int],
    ) -> None:
        """
        Verifica si `operando` alcanzó su último índice de uso (`last use`) en `indice_actual`
        (o si era una constante inmediata efímera) y libera su registro físico.
        """
        if reg_operando is None:
            return
        ocupante = self.descriptor_registros.get(reg_operando)
        if ocupante is None:
            return

        if ocupante.startswith("imm_"):
            self._liberar_registro(
                reg_operando,
                f"constante inmediata efímera en cuádrupla #{indice_actual}",
            )
            return

        if isinstance(operando, str) and ocupante == operando:
            if self._es_temporal(operando) and ultimo_uso.get(operando, -1) <= indice_actual:
                self._liberar_registro(
                    reg_operando,
                    f"último uso del temporal '{operando}' alcanzado en cuádrupla #{indice_actual}",
                )
            elif not self._es_temporal(operando):
                # Las variables de usuario residen en memoria de Stack Frame; liberamos el registro de trabajo
                # tras la operación para dejar los registros R0-R2 disponibles a los temporales vivos
                self._liberar_registro(
                    reg_operando,
                    f"copia en registro de variable '{operando}' completada en cuádrupla #{indice_actual}",
                )

    def generar(self, cuadruplas: List[Cuadrupla]) -> ResultadoCodegen:
        """
        Traduce las cuádruplas TAC a ensamblador aplicando análisis de *liveness* (`ultimo_uso`),
        liberación/reutilización automática de registros y *Spill* a `0x2000+`.
        """
        self._reiniciar_estado()
        ultimo_uso = self.calcular_ultimo_uso(cuadruplas)

        self.instrucciones_asm.append(
            "; === CÓDIGO OBJETIVO STAGELANG (POOL DE REGISTROS FÍSICOS: R0, R1, R2) ==="
        )

        for idx, cuad in enumerate(cuadruplas):
            op = cuad.op

            if op == "ESCENA_INICIO":
                self.instrucciones_asm.append(f"\nSCENE_ENTER {cuad.resultado}:")
                continue

            if op == "ESCENA_FIN":
                self.instrucciones_asm.append(f"SCENE_LEAVE {cuad.resultado}\n")
                continue

            if op == "=":
                reg_origen = self._cargar_operando(cuad.arg1, idx, ultimo_uso)

                if self._es_temporal(cuad.resultado):
                    # El registro pasa a pertenecer al nuevo temporal destino
                    self._vincular_registro(reg_origen, cuad.resultado)
                else:
                    # Variable de usuario: almacenamos en su celda de memoria y liberamos el registro
                    self.instrucciones_asm.append(
                        f"    STORE   [{cuad.resultado}], {reg_origen}"
                    )
                    self._liberar_operando_si_ultimo_uso(
                        cuad.arg1, reg_origen, idx, ultimo_uso
                    )
                continue

            if op in ("+", "-", "*", "/"):
                mnemonico = self.MAPA_MNEMONICOS[op]

                # 1. Cargamos arg1 en un registro físico
                reg_izq = self._cargar_operando(cuad.arg1, idx, ultimo_uso)

                # 2. Cargamos o preparamos arg2 protegiendo reg_izq
                if isinstance(cuad.arg2, (int, float)):
                    op_der_str = str(cuad.arg2)
                    reg_der = None
                else:
                    reg_der = self._cargar_operando(
                        cuad.arg2, idx, ultimo_uso, protegidos=(reg_izq,)
                    )
                    op_der_str = reg_der

                # 3. Antes de pedir registro para `cuad.resultado`, liberamos por LIVENESS
                # los registros de `arg1` y/o `arg2` si esta cuádrupla es su último uso.
                # De este modo el registro recién liberado se reutiliza in-place para `resultado`.
                libero_izq = False
                if (
                    isinstance(cuad.arg1, str)
                    and self._es_temporal(cuad.arg1)
                    and ultimo_uso.get(cuad.arg1, -1) <= idx
                ):
                    self._liberar_registro(
                        reg_izq,
                        f"último uso del temporal '{cuad.arg1}' en cuádrupla #{idx}",
                    )
                    libero_izq = True
                elif isinstance(cuad.arg1, str) and not self._es_temporal(cuad.arg1):
                    self._liberar_registro(
                        reg_izq,
                        f"variable '{cuad.arg1}' leída en cuádrupla #{idx}",
                    )
                    libero_izq = True

                # Adquirimos el registro destino (si reg_izq acaba de liberarse, lo reutilizará sin MOV extra)
                protegidos_dest = (
                    (reg_der,)
                    if (libero_izq and reg_der)
                    else ((reg_izq, reg_der) if reg_der else (reg_izq,))
                )
                reg_dest = self._adquirir_registro(
                    cuad.resultado, idx, ultimo_uso, protegidos=protegidos_dest
                )

                if reg_dest != reg_izq:
                    self.instrucciones_asm.append(f"    MOV     {reg_dest}, {reg_izq}")

                self.instrucciones_asm.append(
                    f"    {mnemonico:<7} {reg_dest}, {op_der_str:<10} ; {cuad.formatear_tac()}"
                )

                # 4. Si arg2 era un temporal en su último uso (o variable leída), liberamos su registro ahora
                if reg_der is not None and reg_der != reg_dest:
                    self._liberar_operando_si_ultimo_uso(
                        cuad.arg2, reg_der, idx, ultimo_uso
                    )
                continue

            if op in ("CANAL", "ESPERA", "MEZCLA"):
                reg_arg1 = self._cargar_operando(cuad.arg1, idx, ultimo_uso)
                mnemonico_cmd = {
                    "CANAL": "OUT_CANAL",
                    "ESPERA": "WAIT_TIME",
                    "MEZCLA": "MIX_FX",
                }[op]
                if cuad.arg2 is not None:
                    reg_arg2 = self._cargar_operando(
                        cuad.arg2, idx, ultimo_uso, protegidos=(reg_arg1,)
                    )
                    self.instrucciones_asm.append(
                        f"    {mnemonico_cmd:<9} {reg_arg1}, {reg_arg2:<10} ; comando {cuad.formatear_tac()}"
                    )
                    self._liberar_operando_si_ultimo_uso(
                        cuad.arg2, reg_arg2, idx, ultimo_uso
                    )
                else:
                    self.instrucciones_asm.append(
                        f"    {mnemonico_cmd:<9} {reg_arg1:<14} ; comando {op.lower()}({cuad.arg1})"
                    )
                self._liberar_operando_si_ultimo_uso(
                    cuad.arg1, reg_arg1, idx, ultimo_uso
                )
                continue

        return ResultadoCodegen(
            instrucciones_asm=list(self.instrucciones_asm),
            tabla_ultimo_uso=ultimo_uso,
            mapa_spill=dict(self.mapa_spill),
            eventos_registros=list(self.eventos_registros),
        )
