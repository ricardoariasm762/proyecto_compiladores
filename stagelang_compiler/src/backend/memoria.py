"""
Fase 3.1 (Back-End): Gestión de Memoria en Tiempo de Ejecución (Stack Frames LIFO y Heap Dinámico).

Implementa `GestorMemoria` con dos regiones de almacenamiento claramente diferenciadas e
integradas en tiempo real con `EmuladorVirtualIR`:
1. **Call Stack (Pila LIFO de Registros de Activación / Stack Frames)**:
   - `push_stack_frame(nombre_contexto)`: Apila un nuevo marco de activación con su dirección
     base (creciendo desde `0x7000`) al iniciar `GLOBAL` o entrar a `escena_<nombre>`.
   - `asignar_local(nombre, valor, es_nueva_local)`: Almacena variables locales o punteros
     en el Stack Frame activo con desplazamientos relativos al Frame Pointer (`FP+0x00`, `FP+0x04`, ...).
   - `obtener_valor(nombre)`: Resuelve jerárquicamente el valor de una variable desde el
     Stack Frame del tope hacia el marco `GLOBAL`.
   - `pop_stack_frame()`: Desapila y destruye automáticamente las variables locales del marco
     al salir de la escena (política LIFO).
2. **Heap Dinámico (Almacenamiento Dinámico con Direcciones Hexadecimales `0x1000+`)**:
   - `reservar_heap(etiqueta, datos, tamano_bytes)`: Reserva un bloque dinámico con dirección
     hexadecimal incremental (`0x1000`, `0x1040`, ...) y retorna el puntero hexadecimal.
   - `liberar_heap(direccion_hex)`: Libera explícitamente el bloque en `direccion_hex` y detecta
     con precisión intentos de **Doble free** o liberación de punteros inválidos.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class ErrorMemoria(Exception):
    """Excepción controlada lanzada ante violaciones de gestión de memoria (Doble free, Stack Underflow, etc.)."""


@dataclass
class VariableLocalSlot:
    """Representa una celda de memoria dentro de un Stack Frame."""

    nombre: str
    valor: Any
    offset_bytes: int
    direccion_hex: str


@dataclass
class StackFrame:
    """Registro de activación individual en la pila LIFO."""

    nombre_contexto: str
    direccion_base: int
    variables: Dict[str, VariableLocalSlot] = field(default_factory=dict)
    punteros_heap_asociados: List[str] = field(default_factory=list)
    siguiente_offset: int = 0

    @property
    def base_hex(self) -> str:
        return f"0x{self.direccion_base:04X}"


@dataclass
class BloqueHeap:
    """Representa un bloque de memoria asignado dinámicamente en el Heap."""

    direccion_hex: str
    etiqueta: str
    datos: Any
    tamano_bytes: int
    activo: bool = True


class GestorMemoria:
    """
    Subsistema de memoria (Stack LIFO + Heap Dinámico) de StageLang.
    Diseñado para operar directamente como el almacenamiento de `EmuladorVirtualIR`.
    """

    def __init__(
        self,
        base_stack: int = 0x7000,
        salto_frame: int = 0x0100,
        base_heap: int = 0x1000,
        auto_iniciar_global: bool = False,
    ) -> None:
        self.base_stack = base_stack
        self.salto_frame = salto_frame
        self.base_heap = base_heap
        self.puntero_heap = base_heap

        self.pila_frames: List[StackFrame] = []
        self.heap: Dict[str, BloqueHeap] = {}
        self.bitacora: List[str] = []

        if auto_iniciar_global:
            self.push_stack_frame("GLOBAL")

    def reiniciar(self) -> None:
        """Limpia la pila de Stack Frames, el Heap y la bitácora."""
        self.puntero_heap = self.base_heap
        self.pila_frames.clear()
        self.heap.clear()
        self.bitacora.clear()

    @property
    def frame_actual(self) -> Optional[StackFrame]:
        """Devuelve el Stack Frame en la cima de la pila o None si está vacía."""
        return self.pila_frames[-1] if self.pila_frames else None

    # =================================================================
    # Operaciones sobre la Pila de Marcos de Activación (Stack LIFO)
    # =================================================================

    def push_stack_frame(self, nombre_contexto: str) -> StackFrame:
        """Apila un nuevo registro de activación (Stack Frame) en orden LIFO."""
        nivel = len(self.pila_frames)
        direccion_base = self.base_stack + (nivel * self.salto_frame)
        nuevo_frame = StackFrame(
            nombre_contexto=nombre_contexto,
            direccion_base=direccion_base,
        )
        self.pila_frames.append(nuevo_frame)
        self.bitacora.append(
            f"[STACK PUSH ] Marco '{nombre_contexto}' apilado en FP={nuevo_frame.base_hex} "
            f"(nivel LIFO={len(self.pila_frames)})"
        )
        return nuevo_frame

    def pop_stack_frame(self, permitir_pop_global: bool = False) -> StackFrame:
        """Desapila el marco de activación en el tope de la pila (LIFO) y destruye sus locales."""
        if not self.pila_frames:
            raise ErrorMemoria("Stack Underflow: la pila de marcos está vacía.")
        if len(self.pila_frames) == 1 and not permitir_pop_global:
            raise ErrorMemoria(
                "Stack Underflow: no se puede desapilar el marco raíz 'GLOBAL' durante la ejecución."
            )
        frame_saliente = self.pila_frames.pop()
        vars_liberadas = list(frame_saliente.variables.keys())
        self.bitacora.append(
            f"[STACK POP  ] Marco '{frame_saliente.nombre_contexto}' (FP={frame_saliente.base_hex}) "
            f"desapilado; variables locales destruidas (LIFO): {vars_liberadas}"
        )
        return frame_saliente

    def asignar_local(
        self,
        nombre: str,
        valor: Any,
        forzar_marco_actual: bool = False,
    ) -> str:
        """
        Asigna o actualiza una variable dentro del Stack Frame activo:
        - Si `forzar_marco_actual` es True o la variable no existe en ningún marco activo,
          crea o actualiza la entrada directamente en la cima del Stack (`pila_frames[-1]`).
        - Si ya existe en el marco actual, actualiza su celda.
        - Si no existe en el marco actual pero sí en un marco padre (`GLOBAL`), la actualiza
          salvo que sea una variable declarada localmente en la escena actual.
        Retorna la dirección hexadecimal asignada en el Stack Frame.
        """
        if not self.pila_frames:
            raise ErrorMemoria("No hay Stack Frames activos para asignar variables.")

        frame_cima = self.pila_frames[-1]

        # 1. Si ya está en la cima del Stack, actualizamos en la cima
        if nombre in frame_cima.variables:
            slot = frame_cima.variables[nombre]
            slot.valor = valor
            self.bitacora.append(
                f"[STACK WRITE] {frame_cima.nombre_contexto}:{nombre} = {valor!r} "
                f"actualizado en {slot.direccion_hex} (FP+0x{slot.offset_bytes:02X})"
            )
            return slot.direccion_hex

        # 2. Si no forzamos marco actual, verificamos si es reasignación de variable global existente
        if not forzar_marco_actual:
            for frame in reversed(self.pila_frames[:-1]):
                if nombre in frame.variables:
                    slot = frame.variables[nombre]
                    slot.valor = valor
                    self.bitacora.append(
                        f"[STACK WRITE] {frame.nombre_contexto}:{nombre} = {valor!r} "
                        f"actualizado en {slot.direccion_hex} (FP+0x{slot.offset_bytes:02X})"
                    )
                    return slot.direccion_hex

        # 3. Alojar nueva variable local en el Stack Frame de la cima
        offset = frame_cima.siguiente_offset
        frame_cima.siguiente_offset += 4
        dir_absoluta = frame_cima.direccion_base + offset
        dir_hex = f"0x{dir_absoluta:04X}"

        frame_cima.variables[nombre] = VariableLocalSlot(
            nombre=nombre,
            valor=valor,
            offset_bytes=offset,
            direccion_hex=dir_hex,
        )
        self.bitacora.append(
            f"[STACK ALLOC] {frame_cima.nombre_contexto}:{nombre} = {valor!r} "
            f"alojado en {dir_hex} (FP+0x{offset:02X})"
        )
        return dir_hex

    def obtener_valor(self, nombre: str) -> Any:
        """
        Busca una variable desde el Stack Frame del tope hacia el marco GLOBAL.
        Lanza KeyError si la variable no existe en ningún Stack Frame activo
        (por ejemplo, si pertenecía a una escena cuyo Stack Frame ya fue desapilado).
        """
        for frame in reversed(self.pila_frames):
            if nombre in frame.variables:
                return frame.variables[nombre].valor
        raise KeyError(
            f"La variable '{nombre}' no existe en ningún Stack Frame activo."
        )

    def registrar_puntero_en_frame_actual(self, nombre_ptr: str, direccion_hex: str) -> str:
        """
        Guarda un puntero hexadecimal de Heap (`0x1000+`) como variable local en el Stack Frame
        actual y lo vincula a la lista de recursos dinámicos de la escena para liberarlo al salir.
        """
        if not self.pila_frames:
            raise ErrorMemoria("No hay Stack Frame activo para registrar puntero de Heap.")
        frame_cima = self.pila_frames[-1]
        frame_cima.punteros_heap_asociados.append(direccion_hex)
        return self.asignar_local(nombre_ptr, direccion_hex, forzar_marco_actual=True)

    # =================================================================
    # Operaciones sobre el Heap Dinámico
    # =================================================================

    def reservar_heap(
        self,
        etiqueta: str,
        datos: Any,
        tamano_bytes: int = 64,
    ) -> str:
        """
        Reserva un bloque en el Heap dinámico y devuelve su dirección hexadecimal (ej. '0x1000').
        """
        if tamano_bytes <= 0:
            raise ErrorMemoria("El tamaño de reserva en Heap debe ser mayor que 0 bytes.")

        dir_hex = f"0x{self.puntero_heap:04X}"
        self.puntero_heap += tamano_bytes

        bloque = BloqueHeap(
            direccion_hex=dir_hex,
            etiqueta=etiqueta,
            datos=datos,
            tamano_bytes=tamano_bytes,
            activo=True,
        )
        self.heap[dir_hex] = bloque
        self.bitacora.append(
            f"[HEAP MALLOC] Bloque '{etiqueta}' ({tamano_bytes}B) reservado en {dir_hex} -> datos={datos!r}"
        )
        return dir_hex

    def liberar_heap(self, direccion_hex: str) -> None:
        """
        Libera un bloque previamente reservado en el Heap.
        Detecta explícitamente intentos de Doble free o direcciones inexistentes.
        """
        if direccion_hex not in self.heap:
            raise ErrorMemoria(
                f"Violación de Heap (Invalid free): la dirección {direccion_hex} nunca fue reservada."
            )

        bloque = self.heap[direccion_hex]
        if not bloque.activo:
            raise ErrorMemoria(
                f"Violación de seguridad en Heap (Doble free detectado): "
                f"el bloque '{bloque.etiqueta}' en la dirección {direccion_hex} ya había sido liberado previamente."
            )

        bloque.activo = False
        bloque.datos = None
        self.bitacora.append(
            f"[HEAP FREE  ] Bloque '{bloque.etiqueta}' en {direccion_hex} liberado correctamente."
        )

    def estado_actual(self) -> str:
        """Genera un resumen visual del estado actual del Stack y del Heap."""
        lineas = ["--- Estado de la Pila de Marcos (Call Stack LIFO) ---"]
        for idx, frame in enumerate(self.pila_frames):
            lineas.append(f"  [{idx}] Frame '{frame.nombre_contexto}' (FP={frame.base_hex}):")
            if not frame.variables:
                lineas.append("      (sin variables locales)")
            for slot in frame.variables.values():
                lineas.append(
                    f"      {slot.direccion_hex} (FP+0x{slot.offset_bytes:02X}): "
                    f"{slot.nombre} = {slot.valor!r}"
                )

        lineas.append("\n--- Estado del Heap Dinámico ---")
        if not self.heap:
            lineas.append("  (sin bloques en Heap)")
        else:
            for bloque in self.heap.values():
                estado = "ACTIVO" if bloque.activo else "LIBERADO"
                lineas.append(
                    f"  {bloque.direccion_hex} [{estado:<8}] ({bloque.tamano_bytes}B) "
                    f"'{bloque.etiqueta}': {bloque.datos!r}"
                )
        return "\n".join(lineas)
