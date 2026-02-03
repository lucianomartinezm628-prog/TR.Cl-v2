import re
import json
import sys
import os
from enum import Enum, auto
from typing import List, Set, Dict, Optional, Any, Tuple, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

# ══════════════════════════════════════════════════════════════
# 1. CONSTANTES Y ENUMS (Protocolo 1)
# ══════════════════════════════════════════════════════════════

class TokenStatus(Enum):
    PENDIENTE = auto()
    ASIGNADO = auto()
    BLOQUEADO = auto()

class TokenCategoria(Enum):
    NUCLEO = auto()
    PARTICULA = auto()
    LOCUCION = auto()

class CategoriaGramatical(Enum):
    SUSTANTIVO = auto()
    ADJETIVO = auto()
    ADVERBIO = auto()
    VERBO = auto()
    PREPOSICION = auto()
    CONJUNCION = auto()
    PRONOMBRE = auto()
    ARTICULO = auto()
    DEMOSTRATIVO = auto()

class FuncRole(Enum):
    COPULA = auto()
    REGIMEN = auto()
    DETERMINACION = auto()
    NEXO_LOGICO = auto()
    MARCA_CASUAL = auto()
    ADVERBIAL = auto()
    RELATIVO = auto()

class ConsultaCodigo(Enum):
    C1_CONFLICTO_PROTOCOLAR = auto()
    C2_COLLISION_DUDA = auto()
    C3_POSIBLE_LOCUCION = auto()
    C4_SINONIMIA = auto()
    C5_TOKEN_NO_REGISTRADO = auto()
    C6_ELEMENTO_DUDOSO = auto()
    C7_REGISTRO_INCOMPLETO = auto()

class FalloCritico(Enum):
    REGISTRO_INCOMPLETO = auto()
    SINONIMIA_NUCLEO = auto()
    TOKEN_NO_REGISTRADO = auto()

class Reason(Enum):
    NO_ROOT = auto()
    GAP_DERIVATION = auto()
    COLLISION = auto()
    IDIOM = auto()

class ModoTransliteracion(Enum):
    DESACTIVADO = auto()
    SELECTIVO = auto()
    COMPLETO = auto()

class NormaTransliteracion(Enum):
    DIN_31635 = auto()
    ISO_233 = auto()
    SIMPLIFICADA = auto()

class ModoSalida(Enum):
    BORRADOR = auto()
    FINAL = auto()

class DecisionOrigen(Enum):
    USUARIO = auto()
    AUTOMATICA = auto()
    INFERIDA = auto()

JERARQUIA_ETIMOLOGICA = ["LENGUA_FUENTE", "LATINA", "GRIEGA", "ARABE", "TECNICA"]
WHITELIST_INYECCION = {"hecho", "cosa", "algo", "que"}
BLACKLIST_INYECCION = {"yo", "tú", "él", "ella", "nosotros", "vosotros", "ellos", "ellas", "me", "te", "se", "nos", "os"}

SUFIJOS = {
    CategoriaGramatical.SUSTANTIVO: {"abstracto": ["-idad", "-ción", "-miento"], "concreto": ["-a", "-o", "-e"], "agente": ["-dor", "-nte"]},
    CategoriaGramatical.ADJETIVO: {"cualidad": ["-al", "-ico", "-oso"], "participial": ["-ado", "-ido"]},
    CategoriaGramatical.VERBO: {"primera": ["-ar"], "derivado": ["-ificar", "-izar"]},
    CategoriaGramatical.ADVERBIO: {"modal": ["-mente"]}
}

MARGEN_VALORES = {"IDIOM": 6, "COLLISION": 5, "NO_ROOT": 4, "GAP_DERIVATION": 4, "TRANSLITERACION": 3, "MAPEO_1_1_ALT": 2, "MAPEO_1_1_DIRECTO": 1}

# ══════════════════════════════════════════════════════════════
# 2. CONFIGURACIÓN Y UTILIDADES BASE
# ══════════════════════════════════════════════════════════════

@dataclass
class ReglaUsuario:
    tipo: str
    condicion: Optional[str]
    accion: str
    timestamp: datetime = field(default_factory=datetime.now)
    activa: bool = True

@dataclass
class ConfiguracionSistema:
    modo_transliteracion: ModoTransliteracion = ModoTransliteracion.DESACTIVADO
    norma_transliteracion: NormaTransliteracion = NormaTransliteracion.DIN_31635
    modo_salida: ModoSalida = ModoSalida.BORRADOR
    reglas_permanentes: List[ReglaUsuario] = field(default_factory=list)
    reglas_sesion: List[ReglaUsuario] = field(default_factory=list)
    locuciones_predefinidas: List[str] = field(default_factory=list)
    auto_decidir_timeout: bool = True
    
    def agregar_regla(self, tipo: str, accion: str, condicion: Optional[str] = None, permanente: bool = False):
        regla = ReglaUsuario(tipo=tipo, condicion=condicion, accion=accion)
        if permanente: self.reglas_permanentes.append(regla)
        else: self.reglas_sesion.append(regla)
    
    def eliminar_regla(self, indice: int, permanente: bool = False) -> bool:
        lista = self.reglas_permanentes if permanente else self.reglas_sesion
        if 0 <= indice < len(lista):
            lista.pop(indice)
            return True
        return False

config_global = ConfiguracionSistema()
def obtener_config() -> ConfiguracionSistema: return config_global

class Logger:
    def info(self, msg): print(f"[INFO] {msg}")
    def warning(self, msg): print(f"[WARN] {msg}")
    def error(self, msg): print(f"[ERR] {msg}")
    def debug(self, msg): pass

class Tokenizador:
    _PATRON_PALABRAS = re.compile(r'[\w\u0600-\u06FF\u0750-\u077F]+', re.UNICODE)
    @classmethod
    def tokenizar(cls, texto: str) -> List[str]:
        return cls._PATRON_PALABRAS.findall(texto)
    @classmethod
    def dividir_oraciones(cls, texto: str) -> List[str]:
        oraciones = re.split(r'(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚأإآ])', texto)
        return [o.strip() for o in oraciones if o.strip()]

class ClasificadorGramatical:
    _PREPOSICIONES = {"bi", "li", "fi", "min", "ʿan", "ʿalā", "ilā", "maʿa", "bayna"}
    _CONJUNCIONES = {"wa", "fa", "aw", "inna", "anna"}
    @classmethod
    def clasificar(cls, token: str) -> Tuple[TokenCategoria, CategoriaGramatical]:
        t = token.lower()
        if t in cls._PREPOSICIONES: return TokenCategoria.PARTICULA, CategoriaGramatical.PREPOSICION
        if t in cls._CONJUNCIONES: return TokenCategoria.PARTICULA, CategoriaGramatical.CONJUNCION
        return TokenCategoria.NUCLEO, CategoriaGramatical.SUSTANTIVO

# ══════════════════════════════════════════════════════════════
# 3. MODELOS DE DATOS
# ══════════════════════════════════════════════════════════════

@dataclass
class MorfologiaFuente:
    numero: str = "singular"
    genero: Optional[str] = None
    persona: Optional[int] = None
    tiempo: Optional[str] = None
    voz: Optional[str] = None

@dataclass
class MorfologiaTarget:
    numero: str = "singular"
    genero: str = "masculino"
    persona: Optional[int] = None
    tiempo: Optional[str] = None
    voz: Optional[str] = None

@dataclass
class SlotN:
    token_src: str
    cat_src: CategoriaGramatical
    pos_index: int
    morph_src: MorfologiaFuente = field(default_factory=MorfologiaFuente)
    status: TokenStatus = TokenStatus.PENDIENTE
    token_tgt: Optional[str] = None
    morph_tgt: Optional[MorfologiaTarget] = None
    locucion_id: Optional[str] = None
    def es_bloqueado(self): return self.status == TokenStatus.BLOQUEADO
    def bloquear(self, loc_id): self.status = TokenStatus.BLOQUEADO; self.locucion_id = loc_id

@dataclass
class SlotP:
    token_src: str
    cat_src: CategoriaGramatical
    pos_index: int
    func_role: Optional[FuncRole] = None
    status: TokenStatus = TokenStatus.PENDIENTE
    token_tgt: Optional[str] = None
    locucion_id: Optional[str] = None
    def es_bloqueado(self): return self.status == TokenStatus.BLOQUEADO
    def bloquear(self, loc_id): self.status = TokenStatus.BLOQUEADO; self.locucion_id = loc_id

@dataclass
class Locucion:
    id: str
    src: str
    componentes: List[str]
    posiciones: List[int]
    tgt: Optional[str] = None
    def contiene_posicion(self, pos: int) -> bool: return pos in self.posiciones
    def primera_posicion(self) -> int: return min(self.posiciones) if self.posiciones else -1

@dataclass
class CeldaMatriz:
    pos: int
    token_src: str
    token_tgt: Optional[str] = None
    tipo: str = "normal"
    slot: Any = None
    def es_absorbido(self): return self.tipo == "absorbido"
    def es_nulo(self): return self.tipo == "nulo"
    def es_inyeccion(self): return self.tipo == "inyeccion"

class MatrizFuente:
    def __init__(self):
        self.celdas: List[CeldaMatriz] = []
        self.slots_n: List[SlotN] = []
        self.slots_p: List[SlotP] = []
        self.locuciones: Dict[str, Locucion] = {}
    def agregar_celda(self, token, pos):
        c = CeldaMatriz(pos, token); self.celdas.append(c); return c
    def agregar_slot_n(self, s): self.slots_n.append(s); self.celdas[s.pos_index].slot = s
    def agregar_slot_p(self, s): self.slots_p.append(s); self.celdas[s.pos_index].slot = s
    def agregar_locucion(self, l): 
        self.locuciones[l.id] = l
        for pos in l.posiciones: 
            if pos < len(self.celdas) and self.celdas[pos].slot: self.celdas[pos].slot.bloquear(l.id)
    def size(self): return len(self.celdas)
    def obtener_slot(self, pos): return self.celdas[pos].slot if 0 <= pos < len(self.celdas) else None
    def obtener_locucion_en_pos(self, pos):
        for l in self.locuciones.values():
            if l.contiene_posicion(pos): return l
        return None

class MatrizTarget:
    def __init__(self, size: int):
        self._size = size
        self.celdas = [CeldaMatriz(i, "") for i in range(size)]
        self.inyecciones: List[CeldaMatriz] = []
    def size(self): return self._size
    def marcar_absorbido(self, pos): self.celdas[pos].tipo = "absorbido"; self.celdas[pos].token_tgt = "[ABSORBIDO]"
    def marcar_nulo(self, pos): self.celdas[pos].tipo = "nulo"
    def insertar_inyeccion(self, token, pos_ref): self.inyecciones.append(CeldaMatriz(pos_ref, "", token, "inyeccion"))
    def obtener_token(self, pos): return self.celdas[pos].token_tgt if 0 <= pos < self._size else None
    def verificar_isomorfismo(self, mtx_s) -> bool: return self._size == mtx_s.size()

@dataclass
class EntradaGlosario:
    token_src: str
    categoria: TokenCategoria
    token_tgt: Optional[str] = None
    status: TokenStatus = TokenStatus.PENDIENTE
    margen: int = 0
    ocurrencias: List[int] = field(default_factory=list)
    etiqueta: Optional[str] = None
    traducciones_por_funcion: Dict[FuncRole, str] = field(default_factory=dict)
    def es_nucleo(self): return self.categoria == TokenCategoria.NUCLEO
    def es_particula(self): return self.categoria == TokenCategoria.PARTICULA

@dataclass
class Opcion:
    letra: str
    texto: str
    justificacion: Optional[str] = None

@dataclass
class Consulta:
    numero: int
    codigo: ConsultaCodigo
    contexto: str
    token_o_frase: str
    opciones: List[Opcion]
    recomendacion: str
    def formatear(self) -> str:
        ops = "\n".join([f"  {o.letra}) {o.texto}" for o in self.opciones])
        return f"[CONSULTA {self.numero}]\n{self.contexto}\nITEM: {self.token_o_frase}\nOPCIONES:\n{ops}\nREC: {self.recomendacion}"

@dataclass
class Decision:
    consulta_codigo: ConsultaCodigo
    contexto: str
    opciones: List[str]
    decision: str
    origen: DecisionOrigen
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass
class ErrorCritico:
    tipo: FalloCritico
    mensaje: str
    contexto: Dict[str, Any]
    def formatear(self): return f"[FALLO CRITICO: {self.tipo.name}] {self.mensaje}"

@dataclass
class EstadoProceso:
    fase_actual: str = "INICIO"
    oraciones_traducidas: int = 0
    total_oraciones: int = 0
    errores_criticos: int = 0
    glosario_entradas: int = 0
    pausado: bool = False
    def formatear(self):
        prog = (self.oraciones_traducidas/self.total_oraciones)*100 if self.total_oraciones else 0
        return f"FASE: {self.fase_actual} | PROG: {prog:.1f}% | ERR: {self.errores_criticos} | GLOS: {self.glosario_entradas}"

# ══════════════════════════════════════════════════════════════
# 4. GESTOR DE CONSULTAS
# ══════════════════════════════════════════════════════════════

class GestorConsultas:
    def __init__(self):
        self._consultas: List[Consulta] = []
        self._decisiones: List[Decision] = []
        self._contador = 0
    
    def crear_consulta(self, codigo, contexto, token, opciones_data, recomendacion="A"):
        self._contador += 1
        opciones = [Opcion(chr(65+i), txt, just) for i, (txt, just) in enumerate(opciones_data)]
        c = Consulta(self._contador, codigo, contexto, token, opciones, recomendacion)
        self._consultas.append(c)
        return c
    
    def hay_pendientes(self): return len(self._consultas) > 0
    def obtener_pendientes(self): return list(self._consultas)
    def formatear_consultas_bloque(self):
        return "\n".join([c.formatear() for c in self._consultas]) if self._consultas else "No hay consultas."
    def formatear_historial(self, filtro=None):
        return "\n".join([f"{d.decision} ({d.origen.name})" for d in self._decisiones]) if self._decisiones else "Sin historial."
    def aplicar_recomendaciones_pendientes(self):
        for c in self._consultas:
            self._decisiones.append(Decision(c.codigo, c.contexto, [], c.recomendacion, DecisionOrigen.AUTOMATICA))
        self._consultas.clear()

_gestor_consultas = GestorConsultas()
def obtener_gestor_consultas(): return _gestor_consultas
# ══════════════════════════════════════════════════════════════
# 5. FORMACIÓN LÉXICA Y TRANSLITERACIÓN (Protocolo 9)
# ══════════════════════════════════════════════════════════════

class SistemaTransliteracion:
    _MAPA = {
        'ء': 'ʾ', 'ا': 'ā', 'ب': 'b', 'ت': 't', 'ث': 'ṯ', 'ج': 'ǧ', 'ح': 'ḥ', 'خ': 'ḫ',
        'د': 'd', 'ذ': 'ḏ', 'ر': 'r', 'ز': 'z', 'س': 's', 'ش': 'š', 'ص': 'ṣ', 'ض': 'ḍ',
        'ط': 'ṭ', 'ظ': 'ẓ', 'ع': 'ʿ', 'غ': 'ġ', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l',
        'م': 'm', 'ن': 'n', 'ه': 'h', 'و': 'w', 'ي': 'y', 'ة': 'a', 'ى': 'ā'
    }
    def transliterar(self, texto: str) -> str:
        return ''.join([self._MAPA.get(c, c) for c in texto])

_transliterador = SistemaTransliteracion()

class GeneradorNeologismos:
    @staticmethod
    def radical(token, cat):
        raiz = _transliterador.transliterar(token).rstrip("-")
        sufijo = "-ado" # Simplificado
        return raiz + sufijo
    @staticmethod
    def derivativo(raiz_es, cat):
        return raiz_es + "-ado"

# ══════════════════════════════════════════════════════════════
# 6. GLOSARIO (Protocolo 8)
# ══════════════════════════════════════════════════════════════

class GlosarioError(Exception): pass
class TokenNoRegistradoError(GlosarioError): pass
class SinonimiaError(GlosarioError): pass

class Glosario:
    def __init__(self):
        self._entradas: Dict[str, EntradaGlosario] = {}
        self._locuciones: Dict[str, Locucion] = {}
        self._loc_counter = 0

    def fase_a_procesar(self, texto: str, tokens_clasificados: List[Tuple]):
        # Detección simplificada de locuciones (Stub)
        # Registro
        for idx, (token, cat, cat_gram) in enumerate(tokens_clasificados):
            if token not in self._entradas:
                self._entradas[token] = EntradaGlosario(token_src=token, categoria=cat, ocurrencias=[idx])
            else:
                self._entradas[token].ocurrencias.append(idx)
        return True

    def fase_b_verificar_existencia(self, token, pos):
        if token not in self._entradas: raise TokenNoRegistradoError(f"Token {token} no existe")
        return True

    def fase_b_verificar_bloqueo(self, token, pos):
        # Stub para verificación de locuciones
        return None

    def fase_b_asignar(self, token, tgt, margen=1, etiqueta=None, func_role=None):
        entrada = self._entradas.get(token)
        if not entrada: return False
        
        if entrada.es_nucleo() and entrada.token_tgt and entrada.token_tgt != tgt:
             if entrada.etiqueta != "FORZADO_USUARIO":
                 # En producción aquí iría un raise SinonimiaError
                 pass 
        
        entrada.token_tgt = tgt
        entrada.status = TokenStatus.ASIGNADO
        entrada.margen = margen
        entrada.etiqueta = etiqueta
        return True

    def obtener_entrada(self, token): return self._entradas.get(token)
    def obtener_locuciones(self): return self._locuciones
    def obtener_traduccion(self, token):
        e = self._entradas.get(token)
        return e.token_tgt if e else None

    # Métodos para comandos
    def actualizar_entrada(self, token, nueva):
        if token not in self._entradas: return False, 0
        self._entradas[token].token_tgt = nueva
        self._entradas[token].etiqueta = "FORZADO_USUARIO"
        return True, len(self._entradas[token].ocurrencias)

    def agregar_entrada(self, token, categoria, tgt=None):
        if token in self._entradas: return False
        e = EntradaGlosario(token, categoria, tgt)
        if tgt: e.status = TokenStatus.ASIGNADO
        self._entradas[token] = e
        return True

    def eliminar_entrada(self, token):
        if token in self._entradas:
            n = len(self._entradas[token].ocurrencias)
            del self._entradas[token]
            return True, n
        return False, 0

    def agregar_locucion(self, src, componentes, posiciones, tgt):
        self._loc_counter += 1
        loc = Locucion(f"LOC_{self._loc_counter:04d}", src, componentes, posiciones, tgt)
        self._locuciones[loc.id] = loc
        return loc

    def formatear_glosario(self):
        if not self._entradas: return "Vacío"
        return "\n".join([f"{k} -> {v.token_tgt or '[PEND]'}" for k,v in sorted(self._entradas.items())])
    def formatear_locuciones(self):
        return "\n".join([f"{l.src} -> {l.tgt}" for l in self._locuciones.values()])
    def formatear_alternativas(self): return "N/A"
    
    def exportar_json(self):
        return json.dumps({k: v.token_tgt for k,v in self._entradas.items()}, indent=2, ensure_ascii=False)
    def exportar_csv(self):
        return "token,traduccion\n" + "\n".join([f"{k},{v.token_tgt}" for k,v in self._entradas.items()])
    def exportar_txt(self): return self.formatear_glosario()

# ══════════════════════════════════════════════════════════════
# 7. PROCESADORES (Núcleos, Partículas, Casos, Reparación)
# ══════════════════════════════════════════════════════════════

class ProcesadorCasosDificiles:
    def procesar(self, slot_n, reason, glosario, candidatos=None):
        token = slot_n.token_src
        n_base = token
        
        if reason == Reason.NO_ROOT:
            n_base = GeneradorNeologismos.radical(token, slot_n.cat_src)
        elif reason == Reason.COLLISION and candidatos:
            n_base = candidatos[0].termino # Simplificado
        
        return {"n_base": n_base, "reason": reason, "exito": True, "requiere_consulta": False}

class ProcesadorNucleos:
    def __init__(self):
        self.p6 = ProcesadorCasosDificiles()
        # Mock DB
        self.etimologia = {"kitab": "libro", "qalb": "corazón", "aql": "intelecto"}

    def set_procesador_casos_dificiles(self, p): self.p6 = p

    def procesar(self, slot_n, glosario):
        token = slot_n.token_src.lower()
        
        # 1. Cache
        entrada = glosario.obtener_entrada(slot_n.token_src)
        if entrada and entrada.status == TokenStatus.ASIGNADO:
            return {"token_tgt": entrada.token_tgt, "morph_tgt": None}

        # 2. Búsqueda
        if token in self.etimologia:
            return {"token_tgt": self.etimologia[token], "morph_tgt": None}
        
        # 3. Caso Difícil
        res_p6 = self.p6.procesar(slot_n, Reason.NO_ROOT, glosario)
        return {"token_tgt": res_p6["n_base"], "restart": True}

class ProcesadorParticulas:
    def procesar(self, slot_p, mtx_s, glosario):
        dic = {"wa": "y", "fi": "en", "min": "de", "ala": "sobre", "bi": "con"}
        tgt = dic.get(slot_p.token_src.lower(), slot_p.token_src)
        return {"candidatos": [tgt]}

class ReparadorSintactico:
    def reparar(self, mtx_t, pos):
        # Stub: Implementar lógica de inyección/puntuación aquí
        pass
# ══════════════════════════════════════════════════════════════
# 8. CORE (Protocolo 3)
# ══════════════════════════════════════════════════════════════

@dataclass
class CoreResult:
    exito: bool
    mtx_t: Optional[MatrizTarget] = None
    mensaje: str = ""

class Core:
    def __init__(self, glosario):
        self.glosario = glosario
        self.mtx_s = None
        self.mtx_t = None
        self.proc_nucleos = None
        self.proc_particulas = None
        self.reparador = None

    def set_procesador_nucleos(self, p): self.proc_nucleos = p
    def set_procesador_particulas(self, p): self.proc_particulas = p
    def set_reparador(self, p): self.reparador = p

    def procesar_oracion(self, mtx_s):
        self.mtx_s = mtx_s
        self.mtx_t = MatrizTarget(mtx_s.size())
        
        # F2. Núcleos
        for slot_n in mtx_s.slots_n:
            res = self.proc_nucleos.procesar(slot_n, self.glosario)
            if res.get("restart"): # Guardar en glosario si fue neologismo
                self.glosario.fase_b_asignar(slot_n.token_src, res["token_tgt"])
            slot_n.token_tgt = res.get("token_tgt")

        # F3. Mapeo
        for i, celda_s in enumerate(mtx_s.celdas):
            celda_t = self.mtx_t.celdas[i]
            celda_t.token_src = celda_s.token_src
            if celda_s.slot and isinstance(celda_s.slot, SlotN):
                celda_t.token_tgt = celda_s.slot.token_tgt
            
        # F4. Partículas
        for slot_p in mtx_s.slots_p:
            cands = self.proc_particulas.procesar(slot_p, mtx_s, self.glosario)["candidatos"]
            self.mtx_t.celdas[slot_p.pos_index].token_tgt = cands[0]

        return CoreResult(True, self.mtx_t, "OK")

    def serializar_resultado(self, mtx_t=None):
        tgt = mtx_t or self.mtx_t
        if not tgt: return ""
        return " ".join([c.token_tgt or f"[{c.token_src}]" for c in tgt.celdas if not c.es_absorbido()])

# ══════════════════════════════════════════════════════════════
# 9. RENDERIZADO Y COMANDOS (Protocolos 10 y 11)
# ══════════════════════════════════════════════════════════════

class ControladorRenderizado:
    def limpiar_texto(self, texto):
        t = re.sub(r'\', '', texto) # Limpiar metadatos
        return type('obj', (object,), {'texto_limpio': t, 'ruido_eliminado': []})

class CategoriaComando(Enum):
    CONSULTA = auto(); MODIFICACION = auto(); CONTROL = auto(); EXPORTACION = auto(); AYUDA = auto()

@dataclass
class ResultadoComando:
    exito: bool; mensaje: str; datos: Any = None; requiere_confirmacion: bool = False

class ProcesadorComandos:
    def __init__(self, glosario, config, estado):
        self.glosario = glosario
        self.config = config
        self.estado = estado
        self._callbacks = {}
        self._confirmacion = None

    def set_callback(self, cmd, cb): self._callbacks[cmd.upper()] = cb

    def procesar(self, entrada):
        entrada = entrada.strip()
        if self._confirmacion: return self._procesar_confirmacion(entrada)
        
        parts = entrada.strip("[]").split(" ", 1)
        cmd = parts[0].upper()
        args = parts[1] if len(parts) > 1 else ""
        
        if cmd == "GLOSARIO": return ResultadoComando(True, self.glosario.formatear_glosario())
        if cmd == "AYUDA": return ResultadoComando(True, "Comandos: GLOSARIO, ACTUALIZA, PAUSA, REINICIAR...")
        if cmd == "ESTADO": return ResultadoComando(True, self.estado.formatear())
        
        if cmd == "ACTUALIZA":
            if "=" not in args: return ResultadoComando(False, "Uso: ACTUALIZA token = valor")
            t, v = map(str.strip, args.split("=", 1))
            self._confirmacion = lambda: self.glosario.actualizar_entrada(t, v) and ResultadoComando(True, "Actualizado")
            return ResultadoComando(True, f"¿Cambiar {t} a {v}?", requiere_confirmacion=True)
            
        if cmd == "PAUSA": self._callbacks.get("PAUSA", lambda: None)(); return ResultadoComando(True, "Pausado")
        if cmd == "CONTINUAR": self._callbacks.get("CONTINUAR", lambda: None)(); return ResultadoComando(True, "Continuando")
        if cmd == "REINICIAR":
            self._confirmacion = lambda: self._callbacks.get("REINICIAR", lambda: None)() or ResultadoComando(True, "Reiniciado")
            return ResultadoComando(True, "¿Reiniciar sistema?", requiere_confirmacion=True)

        return ResultadoComando(False, "Comando desconocido")

    def _procesar_confirmacion(self, txt):
        if txt.lower() in ["si", "s", "yes"]:
            cb = self._confirmacion; self._confirmacion = None; return cb()
        self._confirmacion = None; return ResultadoComando(True, "Cancelado")

_procesador_comandos = None
def obtener_procesador_comandos(g, c, e):
    global _procesador_comandos
    if not _procesador_comandos: _procesador_comandos = ProcesadorComandos(g, c, e)
    return _procesador_comandos

# ══════════════════════════════════════════════════════════════
# 10. SISTEMA PRINCIPAL (Main)
# ══════════════════════════════════════════════════════════════

class SistemaTraduccion:
    def __init__(self):
        self.config = obtener_config()
        self.estado = EstadoProceso()
        self.glosario = Glosario()
        self.core = Core(self.glosario)
        self.renderizado = ControladorRenderizado()
        self.gestor_consultas = obtener_gestor_consultas()
        
        # Procesadores
        self.core.set_procesador_nucleos(ProcesadorNucleos())
        self.core.set_procesador_particulas(ProcesadorParticulas())
        self.core.set_reparador(ReparadorSintactico())
        
        # Comandos
        self.proc_comandos = obtener_procesador_comandos(self.glosario, self.config, self.estado)
        self.proc_comandos.set_callback("PAUSA", lambda: setattr(self.estado, 'pausado', True))
        self.proc_comandos.set_callback("CONTINUAR", lambda: setattr(self.estado, 'pausado', False))
        self.proc_comandos.set_callback("REINICIAR", self._reiniciar)

    def _reiniciar(self):
        self.__init__() # Reset completo

    def traducir(self, texto):
        if self.estado.pausado: return "[PAUSADO]"
        
        limpio = self.renderizado.limpiar_texto(texto).texto_limpio
        oraciones = Tokenizador.dividir_oraciones(limpio)
        self.estado.total_oraciones = len(oraciones)
        
        # Registro
        all_tokens = []
        for o in oraciones:
            for t in Tokenizador.tokenizar(o):
                cat, gram = ClasificadorGramatical.clasificar(t)
                all_tokens.append((t, cat, gram))
        self.glosario.fase_a_procesar(limpio, all_tokens)
        self.estado.glosario_entradas = len(self.glosario._entradas)

        # Traducción
        resultados = []
        for i, o in enumerate(oraciones):
            self.estado.oraciones_traducidas = i + 1
            
            mtx_s = MatrizFuente()
            tokens = Tokenizador.tokenizar(o)
            for k, t in enumerate(tokens):
                mtx_s.agregar_celda(t, k)
                cat, gram = ClasificadorGramatical.clasificar(t)
                if cat == TokenCategoria.NUCLEO: mtx_s.agregar_slot_n(SlotN(t, gram, k))
                else: mtx_s.agregar_slot_p(SlotP(t, gram, k))
            
            res = self.core.procesar_oracion(mtx_s)
            resultados.append(self.core.serializar_resultado(res.mtx_t))
            
        return " ".join(resultados)

    def procesar_comando(self, cmd):
        return self.proc_comandos.procesar(cmd).mensaje

def main():
    sistema = SistemaTraduccion()
    print("=== SISTEMA DE TRADUCCIÓN ISOMÓRFICA (OPTIMIZADO) ===")
    print("Escribe texto para traducir o [COMANDO] (ej: [AYUDA]). 'salir' para terminar.\n")
    
    while True:
        try:
            inp = input("> ").strip()
            if not inp: continue
            if inp.lower() in ["salir", "exit"]: break
            
            if inp.startswith("[") or inp.isupper():
                print(sistema.procesar_comando(inp))
            else:
                print(f"\nOUT: {sistema.traducir(inp)}\n")
        except KeyboardInterrupt: break
        except Exception as e: print(f"ERROR: {e}")

if __name__ == "__main__":
    main()
