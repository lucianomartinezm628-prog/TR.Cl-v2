import streamlit as st
import google.generativeai as genai
import json
import pandas as pd
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from enum import Enum
import uuid

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Sistema de Traducción Isomórfica (P0)",
    layout="wide",
    initial_sidebar_state="expanded",
    page_icon="🛡️"
)

# --- CONSTANTES Y ENUMS (constants.py) ---

class TokenStatus(str, Enum):
    PENDIENTE = "PENDIENTE"   # Nuevo, requiere análisis
    ASIGNADO = "ASIGNADO"     # En glosario, inmutable
    CONFLICTO = "CONFLICTO"   # Diferencia entre Glosario y Propuesta
    REVISAR = "REVISAR"       # Duda del modelo (C6)
    BLOQUEADO = "BLOQUEADO"   # Parte de frase idiomática

class TokenCategoria(str, Enum):
    NUCLEO = "NUCLEO"      # Sust, Adj, Verb, Adv
    PARTICULA = "PARTICULA" # Prep, Conj, Pron
    LOCUCION = "LOCUCION"   # Unidad compleja
    SIGNO = "SIGNO"         # Puntuación

class CategoriaGramatical(str, Enum):
    SUSTANTIVO = "SUSTANTIVO"
    VERBO = "VERBO"
    ADJETIVO = "ADJETIVO"
    ADVERBIO = "ADVERBIO"
    PREPOSICION = "PREPOSICION"
    CONJUNCION = "CONJUNCION"
    PRONOMBRE = "PRONOMBRE"
    OTRO = "OTRO"

# --- MODELOS DE DATOS (models.py) ---

@dataclass
class TokenData:
    """Representación de un token individual (Slot_N / Slot_P)"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    source: str = ""
    target_propuesto: str = ""
    target_final: str = ""
    categoria: TokenCategoria = TokenCategoria.NUCLEO
    gramatica: CategoriaGramatical = CategoriaGramatical.OTRO
    raiz_etimologica: Optional[str] = None
    status: TokenStatus = TokenStatus.PENDIENTE
    confianza_ai: float = 0.0
    nota_ai: str = "" # Explicación breve de Gemini

@dataclass
class TranslationContext:
    """Estado global de la traducción actual"""
    texto_fuente: str = ""
    matriz_tokens: List[TokenData] = field(default_factory=list)
    alertas: List[Dict] = field(default_factory=list)
    is_processed: bool = False
# --- GESTOR DE GLOSARIO (glossary.py) ---

class GestorGlosario:
    def __init__(self):
        # Inicializar en session_state si no existe
        if 'glosario_db' not in st.session_state:
            st.session_state['glosario_db'] = {}
            # Carga inicial simulada o vacía
    
    def buscar_token(self, token_src: str) -> Optional[Dict]:
        """Busca coincidencia exacta en el glosario (P8.A)"""
        db = st.session_state['glosario_db']
        return db.get(token_src.strip().lower())

    def registrar_o_validar(self, token: TokenData) -> TokenData:
        """
        Aplica lógica P8:
        1. Si existe -> Impone traducción del glosario (Sobreescribe propuesta AI).
        2. Si no existe -> Marca como PENDIENTE para revisión humana o auto-asignación.
        3. Si hay discrepancia -> Marca CONFLICTO.
        """
        entry = self.buscar_token(token.source)
        
        if entry:
            # CASO: YA EXISTE EN GLOSARIO
            trad_glosario = entry['target']
            
            if token.target_propuesto and token.target_propuesto.lower() != trad_glosario.lower():
                # La IA propone algo diferente al glosario -> CONFLICTO
                # Pero según protocolo, Glosario manda, a menos que P0 decida.
                # Marcamos conflicto para visibilidad, pero pre-llenamos con Glosario.
                token.status = TokenStatus.CONFLICTO
                token.nota_ai = f"Glosario dice '{trad_glosario}', IA propuso '{token.target_propuesto}'"
                token.target_final = trad_glosario # Default al glosario
            else:
                token.status = TokenStatus.ASIGNADO
                token.target_final = trad_glosario
                token.nota_ai = "Validado por Glosario"
        else:
            # CASO: NUEVO
            token.status = TokenStatus.PENDIENTE
            token.target_final = token.target_propuesto # Propuesta inicial
            
        return token

    def guardar_decision(self, token_src: str, token_tgt: str, categoria: str):
        """Sella una decisión en el glosario (P11)"""
        st.session_state['glosario_db'][token_src.strip().lower()] = {
            'target': token_tgt.strip(),
            'categoria': categoria,
            'fecha': '2026-02-03' # Timestamp simulado
        }
# --- INTERFAZ GEMINI (consultas.py) ---

SYSTEM_PROMPT = """
ACTÚA COMO EL MOTOR DE PROCESAMIENTO DE UN SISTEMA DE TRADUCCIÓN ISOMÓRFICA (PROTOCOLO P1-P10).
TU ROL: Analizar el texto fuente, tokenizarlo gramaticalmente y proponer equivalencias 1:1 estrictas.

REGLAS FUNDAMENTALES:
1. Isomorfismo: Mantén la posición y cantidad de palabras exacta.
2. Literalidad: Prioriza la raíz etimológica sobre el estilo.
3. Clasificación: Identifica si es NUCLEO (Sust/Verb/Adj) o PARTICULA.
4. Salida: DEBES RESPONDER ÚNICAMENTE EN FORMATO JSON VÁLIDO.

Estructura JSON requerida:
[
  {
    "source": "palabra_fuente",
    "target_propuesto": "palabra_español",
    "categoria": "NUCLEO" | "PARTICULA" | "SIGNO",
    "gramatica": "SUSTANTIVO" | "VERBO" | "PREPOSICION" | ... ,
    "raiz": "raiz_etimologica_si_aplica",
    "explicacion": "breve razon"
  },
  ...
]
"""

class GeminiEngine:
    def __init__(self, api_key: str, model_name: str):
        if not api_key:
            raise ValueError("Falta API Key")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=SYSTEM_PROMPT
        )
    
    def analizar_texto(self, texto: str) -> List[Dict]:
        """Envía el texto a Gemini y espera un JSON estructurado"""
        try:
            prompt = f"ANALIZAR ESTE TEXTO:\n\n{texto}\n\nGenera el JSON de mapeo isomorfico:"
            response = self.model.generate_content(prompt)
            
            # Limpieza básica por si el modelo añade markdown ```json
            clean_text = response.text.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_text)
            return data
        except Exception as e:
            st.error(f"Error fatal en Gemini: {str(e)}")
            return []

# --- NÚCLEO DEL SISTEMA (main logic) ---

class SistemaTraduccion:
    def __init__(self, api_key, model_name):
        self.engine = GeminiEngine(api_key, model_name)
        self.glosario = GestorGlosario()
        
    def procesar(self, texto: str) -> TranslationContext:
        ctx = TranslationContext(texto_fuente=texto)
        
        # 1. Operación AI (Gemini tokeniza y propone)
        raw_data = self.engine.analizar_texto(texto)
        
        # 2. Conversión a objetos internos y Validación con Glosario
        for item in raw_data:
            token = TokenData(
                source=item.get('source', ''),
                target_propuesto=item.get('target_propuesto', ''),
                categoria=TokenCategoria(item.get('categoria', 'NUCLEO')),
                gramatica=CategoriaGramatical(item.get('gramatica', 'OTRO')),
                raiz_etimologica=item.get('raiz', ''),
                nota_ai=item.get('explicacion', '')
            )
            
            # 3. Supervisión Automática (Check Glosario)
            token = self.glosario.registrar_o_validar(token)
            ctx.matriz_tokens.append(token)
            
        ctx.is_processed = True
        return ctx
# --- INTERFAZ DE USUARIO (Streamlit) ---

def render_ui():
    # --- SIDEBAR: CONTROL ---
    with st.sidebar:
        st.header("⚙️ Sala de Máquinas")
        
        # API KEY (Segura)
        api_key = st.text_input("Gemini API Key", type="password")
        
        # SELECTOR DE MODELOS (Tu lista completa)
        modelos = [
            "gemini-2.0-flash", "gemini-2.0-flash-lite", 
            "gemini-2.5-flash", "gemini-2.5-pro",
            "gemini-2.0-flash-001", "gemini-2.0-flash-lite-001",
            "gemini-exp-1206", "deep-research-pro-preview-12-2025",
            "gemma-3-27b-it", "gemini-1.5-pro"
        ]
        modelo = st.selectbox("Modelo Activo", modelos)
        
        st.divider()
        st.markdown("### 📊 Estadísticas")
        st.info(f"Glosario: {len(st.session_state.get('glosario_db', {}))} términos")

    st.title("🛡️ Estación de Custodia P0")
    st.markdown("_El sistema opera, el humano supervisa._")

    # --- 1. INPUT ---
    st.subheader("1. Texto Fuente")
    texto_input = st.text_area("Ingresa el texto para traducir:", height=100)
    
    col_acc1, col_acc2 = st.columns([1, 5])
    
    if col_acc1.button("🚀 PROCESAR", use_container_width=True):
        if not api_key:
            st.error("Se requiere API Key")
        elif not texto_input:
            st.warning("Texto vacío")
        else:
            with st.spinner(f"Gemini ({modelo}) operando protocolos P1-P10..."):
                sistema = SistemaTraduccion(api_key, modelo)
                # Guardar resultado en estado para no perderlo al interactuar
                st.session_state['ctx_actual'] = sistema.procesar(texto_input)

    # --- 2. ZONA DE CUSTODIA (SUPERVISIÓN) ---
    if 'ctx_actual' in st.session_state:
        ctx = st.session_state['ctx_actual']
        
        st.divider()
        st.subheader("2. Panel de Supervisión (Matriz Isomórfica)")
        
        # Filtros de visualización
        filtro = st.radio("Mostrar:", ["Todos", "Conflictos", "Pendientes"], horizontal=True)
        
        # Convertir a DataFrame para edición fácil
        data_editor = []
        for t in ctx.matriz_tokens:
            show = True
            if filtro == "Conflictos" and t.status != TokenStatus.CONFLICTO: show = False
            if filtro == "Pendientes" and t.status != TokenStatus.PENDIENTE: show = False
            
            if show:
                data_editor.append({
                    "ID": t.id,
                    "Estado": t.status.value,
                    "Origen": t.source,
                    "Propuesta AI": t.target_propuesto,
                    "Traducción Final (Editable)": t.target_final,
                    "Categoría": t.categoria.value,
                    "Nota AI": t.nota_ai
                })
        
        if data_editor:
            df = pd.DataFrame(data_editor)
            
            # CONFIGURACIÓN DE COLORES SEGÚN ESTADO
            def color_status(val):
                color = 'white'
                if val == 'CONFLICTO': color = '#ffcccc' # Rojo suave
                elif val == 'PENDIENTE': color = '#fff4cc' # Amarillo suave
                elif val == 'ASIGNADO': color = '#ccffcc' # Verde suave
                return f'background-color: {color}'

            # EDITOR DE DATOS INTERACTIVO
            edited_df = st.data_editor(
                df,
                column_config={
                    "Estado": st.column_config.TextColumn(disabled=True),
                    "Origen": st.column_config.TextColumn(disabled=True),
                    "Propuesta AI": st.column_config.TextColumn(disabled=True),
                    "Traducción Final (Editable)": st.column_config.TextColumn(required=True),
                },
                disabled=["ID", "Estado", "Origen", "Propuesta AI", "Nota AI"],
                hide_index=True,
                use_container_width=True,
                key="editor_datos"
            )
            
            # --- BOTONES DE ACCIÓN ---
            col_b1, col_b2 = st.columns(2)
            
            # Acción: APROBAR Y GUARDAR EN GLOSARIO
            if col_b1.button("✅ Aprobar y Actualizar Glosario"):
                cambios_cnt = 0
                glosario_manager = GestorGlosario()
                
                # Iteramos sobre el DF editado para actualizar el estado real
                for index, row in edited_df.iterrows():
                    token_id = row['ID']
                    nuevo_target = row['Traducción Final (Editable)']
                    
                    # Buscar el token original en el objeto
                    token_obj = next((x for x in ctx.matriz_tokens if x.id == token_id), None)
                    
                    if token_obj:
                        token_obj.target_final = nuevo_target
                        # Si era pendiente o conflicto, ahora se consagra
                        if token_obj.status in [TokenStatus.PENDIENTE, TokenStatus.CONFLICTO]:
                            glosario_manager.guardar_decision(
                                token_obj.source, 
                                nuevo_target, 
                                token_obj.categoria.value
                            )
                            token_obj.status = TokenStatus.ASIGNADO
                            cambios_cnt += 1
                
                st.success(f"Se actualizaron {cambios_cnt} términos en el Glosario.")
                st.rerun() # Recargar para ver los estados en verde

        else:
            st.info("No hay tokens que coincidan con el filtro seleccionado.")

        # --- 3. OUTPUT FINAL ---
        st.divider()
        st.subheader("3. Salida Renderizada (Texto Final)")
        
        # Reconstrucción simple (se puede mejorar con lógica de puntuación P10.B)
        texto_final = " ".join([t.target_final for t in ctx.matriz_tokens])
        st.code(texto_final, language="text")
        
        # Opción de descarga
        st.download_button("Descargar Traducción", texto_final, "traduccion.txt")
        
        # Opción de exportar glosario
        if st.expander("Ver JSON del Glosario Actual"):
            st.json(st.session_state['glosario_db'])

# EJECUCIÓN PRINCIPAL
if __name__ == "__main__":
    render_ui()
