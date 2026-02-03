import streamlit as st
import google.generativeai as genai
import json
import pandas as pd
import time
import re
from datetime import datetime

# ==============================================================================
# 1. CONFIGURACIÓN DE PÁGINA Y ESTILOS
# ==============================================================================
st.set_page_config(
    layout="wide", 
    page_title="Sistema de Traducción Isomórfica", 
    page_icon="🛡️"
)

st.markdown("""
<style>
    .stTextArea textarea { font-family: 'Courier New', monospace; font-size: 16px; }
    .status-box { padding: 15px; border-radius: 8px; margin-bottom: 10px; border: 1px solid #ddd; }
    .status-nuevo { background-color: #e3f2fd; border-color: #90caf9; color: #0d47a1; }
    .status-conflicto { background-color: #ffebee; border-color: #ef9a9a; color: #b71c1c; }
    .status-ok { background-color: #e8f5e9; border-color: #a5d6a7; color: #1b5e20; }
    .metric-card { background-color: #f8f9fa; padding: 10px; border-radius: 5px; border: 1px solid #eee; text-align: center; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. GESTIÓN DE ESTADO (SESSION STATE)
# ==============================================================================
if "glosario" not in st.session_state:
    # { "token": { "target": "traducción", "tipo": "CATEGORIA", "fecha": "YYYY-MM-DD" } }
    st.session_state.glosario = {} 

if "estado_actual" not in st.session_state:
    st.session_state.estado_actual = "ESPERANDO_INPUT" # Estados: ESPERANDO_INPUT, CUSTODIA, FINALIZADO

if "datos_temporales" not in st.session_state:
    st.session_state.datos_temporales = None

# ==============================================================================
# 3. LA CONSTITUCIÓN (SYSTEM PROMPT)
# ==============================================================================
SYSTEM_INSTRUCTION = """
ERES EL MOTOR DE PROCESAMIENTO DE UN SISTEMA DE TRADUCCIÓN ISOMÓRFICA (P1-P11).
TU OBJETIVO ES CUMPLIR ESTRICTAMENTE LOS PROTOCOLOS. NO SEAS CONVERSACIONAL.

--- PROTOCOLOS FUNDAMENTALES ---
P1 (ISOMORFISMO): La traducción debe mantener una correspondencia 1:1 estricta con los tokens fuente.
P2 (AUTORIDAD): El Usuario (P0) es la autoridad. Ante duda o palabra desconocida, marca CONFLICTO/NUEVO.
P4 (NÚCLEOS): Sustantivos, Verbos, Adjetivos son INVARIABLES una vez fijados en el Glosario.
    - Prioridad: Etimología > Uso Técnico.
    - Si no existe raíz: Usar Transliteración + Sufijo Español.
P5 (PARTÍCULAS): Preposiciones/Conjunciones son POLIVALENTES (dependen de la función).
P8 (GLOSARIO): 
    - Consultar SIEMPRE el glosario inyectado.
    - Si el token está en el glosario, USAR esa traducción OBLIGATORIAMENTE.
    - Si el token es nuevo, proponer traducción basada en etimología.

--- INSTRUCCIONES DE SALIDA (JSON) ---
Responde ÚNICAMENTE con un objeto JSON válido con esta estructura:

{
  "analisis": [
    {
      "token_origen": "palabra_fuente",
      "token_destino_propuesto": "palabra_destino",
      "categoria": "NUCLEO" | "PARTICULA" | "LOCUCION",
      "razonamiento": "Breve explicación etimológica o regla aplicada",
      "estado": "OK" | "CONFLICTO" | "NUEVO"
    }
  ],
  "traduccion_borrador": "La frase completa traducida",
  "requiere_custodia": true | false
}

REGLA DE ORO: Si encuentras un NÚCLEO que no está en el glosario, marca estado="NUEVO" y requiere_custodia=true.
"""

# ==============================================================================
# 4. LÓGICA DEL NÚCLEO (API & PROCESAMIENTO)
# ==============================================================================

def limpiar_json(texto_respuesta):
    """Limpia bloques de código Markdown si Gemini los incluye."""
    if "```json" in texto_respuesta:
        texto_respuesta = texto_respuesta.replace("```json", "").replace("```", "")
    elif "```" in texto_respuesta:
        texto_respuesta = texto_respuesta.replace("```", "")
    return texto_respuesta.strip()

def obtener_glosario_formateado():
    """Convierte el glosario de memoria a texto para el prompt."""
    if not st.session_state.glosario:
        return "GLOSARIO VACÍO (No hay términos registrados)."
    
    texto = "GLOSARIO ACTUAL (OBLIGATORIO RESPETAR):\n"
    for token, datos in st.session_state.glosario.items():
        texto += f"- {token} --> {datos['target']} ({datos['tipo']})\n"
    return texto

def consultar_gemini_seguro(prompt_usuario, api_key, modelo):
    """
    Realiza la consulta a la API con manejo robusto de errores 429 (Rate Limits)
    y limpieza de JSON.
    """
    genai.configure(api_key=api_key)
    
    prompt_completo = f"""
    {obtener_glosario_formateado()}
    
    INPUT DEL USUARIO (TEXTO FUENTE A TRADUCIR):
    "{prompt_usuario}"
    
    Analiza token por token. Verifica contra el glosario. Genera el JSON de respuesta.
    """

    # Configuración de generación para forzar JSON (donde sea soportado) o texto estructurado
    generation_config = {
        "temperature": 0.1, # Baja temperatura para mayor precisión
        "response_mime_type": "application/json"
    }

    model = genai.GenerativeModel(
        model_name=modelo,
        system_instruction=SYSTEM_INSTRUCTION,
        generation_config=generation_config
    )

    # Bucle de reintentos (Backoff Exponencial)
    max_intentos = 3
    espera_inicial = 2

    for intento in range(max_intentos):
        try:
            with st.spinner(f"Gemini ({modelo}) procesando protocolos... (Intento {intento+1})"):
                response = model.generate_content(prompt_completo)
                
                # Validación y Limpieza
                texto_limpio = limpiar_json(response.text)
                return json.loads(texto_limpio)
                
        except Exception as e:
            error_msg = str(e)
            
            # Manejo específico de error 429 (Too Many Requests)
            if "429" in error_msg:
                wait_time = espera_inicial * (2 ** intento) # 2s, 4s, 8s
                st.toast(f"⏳ Tráfico alto en API (Error 429). Reintentando en {wait_time}s...", icon="⚠️")
                time.sleep(wait_time)
                continue # Volver al inicio del bucle
            
            # Manejo de error 404 (Modelo no encontrado)
            elif "404" in error_msg:
                st.error(f"❌ El modelo '{modelo}' no está disponible o no es compatible en esta ruta. Por favor selecciona otro modelo de la lista.")
                return None
            
            # Otros errores
            else:
                st.error(f"Error inesperado en Gemini: {error_msg}")
                return None
    
    st.error("❌ Se agotaron los reintentos. El servicio está saturado temporalmente.")
    return None

def registrar_en_glosario(token, traduccion, categoria):
    """Guarda un término validado en el glosario."""
    st.session_state.glosario[token] = {
        "target": traduccion,
        "tipo": categoria,
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M")
    }

# ==============================================================================
# 5. INTERFAZ DE USUARIO (SIDEBAR)
# ==============================================================================
with st.sidebar:
    st.header("⚙️ Configuración del Motor")
    
    api_key_input = st.text_input("Gemini API Key", type="password")
    
    # LISTA EXACTA PROPORCIONADA POR EL USUARIO
    modelos_disponibles = [
        "gemini-flash-latest",            # <--- RECOMENDADO (Alias estable)
        "gemini-flash-lite-latest",
        "gemini-2.0-flash-lite",          # <--- RECOMENDADO (Bajo consumo)
        "gemini-2.0-flash",               # Potente pero estricto con cuotas
        "gemini-2.0-flash-001",
        "gemini-2.5-flash",               # Preview (puede ser lento)
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
        "gemini-exp-1206",
        "gemini-pro-latest",
        "gemini-3-flash-preview",         # Preview v3
        "gemma-3-27b-it"
    ]
    
    # Selección de modelo con un default seguro (Flash Latest)
    modelo_seleccionado = st.selectbox(
        "Modelo Activo", 
        modelos_disponibles, 
        index=0, 
        help="Si recibes errores 429, usa versiones 'Lite' o 'Latest'."
    )
    
    st.divider()
    
    # Panel de Glosario
    st.subheader(f"📚 Glosario ({len(st.session_state.glosario)})")
    if st.session_state.glosario:
        # Convertir a DF para visualización limpia
        data_glosario = []
        for k, v in st.session_state.glosario.items():
            data_glosario.append({"Token": k, "Traducción": v["target"], "Tipo": v["tipo"]})
        st.dataframe(pd.DataFrame(data_glosario), hide_index=True, use_container_width=True)
        
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            if st.button("Descargar JSON"):
                st.download_button(
                    label="📥 JSON",
                    data=json.dumps(st.session_state.glosario, indent=2),
                    file_name="glosario_isomorfico.json",
                    mime="application/json"
                )
        with col_g2:
            if st.button("🗑️ Borrar Todo"):
                st.session_state.glosario = {}
                st.rerun()
    else:
        st.info("El glosario está vacío. Se llenará automáticamente al procesar textos.")

# ==============================================================================
# 6. INTERFAZ PRINCIPAL (WORKFLOW)
# ==============================================================================
st.title("🛡️ Sistema de Traducción Isomórfica")
st.caption(f"Operando con: **{modelo_seleccionado}** | Protocolos P1-P11 Activos")

# --- FASE 1: INPUT ---
if st.session_state.estado_actual == "ESPERANDO_INPUT":
    st.markdown("### 1. Entrada de Texto Fuente")
    texto_usuario = st.text_area("Ingresa el texto (Árabe, Técnico, Filosófico):", height=150)
    
    col_act1, col_act2 = st.columns([1, 4])
    with col_act1:
        if st.button("🚀 PROCESAR", type="primary", use_container_width=True):
            if not api_key_input:
                st.error("⚠️ Se requiere API Key en la barra lateral.")
            elif not texto_usuario.strip():
                st.warning("⚠️ El texto está vacío.")
            else:
                # LLAMADA AL NÚCLEO
                respuesta = consultar_gemini_seguro(texto_usuario, api_key_input, modelo_seleccionado)
                
                if respuesta:
                    st.session_state.datos_temporales = respuesta
                    
                    # Decisión de Flujo: ¿Custodia o Directo?
                    if respuesta.get("requiere_custodia", False):
                        st.session_state.estado_actual = "CUSTODIA"
                    else:
                        # Si es todo OK, registramos lo NUEVO automáticamente y finalizamos
                        count_nuevos = 0
                        for item in respuesta.get("analisis", []):
                            if item["estado"] == "NUEVO":
                                registrar_en_glosario(item["token_origen"], item["token_destino_propuesto"], item["categoria"])
                                count_nuevos += 1
                        
                        if count_nuevos > 0:
                            st.toast(f"Se registraron {count_nuevos} términos nuevos automáticamente.", icon="📚")
                        
                        st.session_state.estado_actual = "FINALIZADO"
                    
                    st.rerun()

# --- FASE 2: CUSTODIA (HUMAN IN THE LOOP) ---
elif st.session_state.estado_actual == "CUSTODIA":
    st.markdown("### 2. Panel de Custodia (P0)")
    st.warning("⚠️ Gemini ha detectado términos nuevos o conflictos que requieren tu autorización.")
    
    datos = st.session_state.datos_temporales
    analisis = datos.get("analisis", [])
    
    # Formulario para resolver conflictos
    with st.form("form_custodia"):
        items_a_revisar = [it for it in analisis if it["estado"] in ["NUEVO", "CONFLICTO"]]
        
        if not items_a_revisar:
            st.info("No hay conflictos reales, aunque el sistema marcó custodia. Puedes avanzar.")
        
        for i, item in enumerate(items_a_revisar):
            # Tarjeta visual para cada conflicto
            clase_css = "status-nuevo" if item["estado"] == "NUEVO" else "status-conflicto"
            icono = "🆕" if item["estado"] == "NUEVO" else "⚔️"
            
            st.markdown(f"""
            <div class="status-box {clase_css}">
                <strong>{icono} {item['estado']}:</strong> Token origen <code>{item['token_origen']}</code> ({item['categoria']})<br>
                <em>Razón AI: {item['razonamiento']}</em>
            </div>
            """, unsafe_allow_html=True)
            
            col_c1, col_c2 = st.columns([1, 1])
            with col_c1:
                # Mostramos la propuesta de la IA
                st.text_input(f"Propuesta IA ({i})", value=item['token_destino_propuesto'], disabled=True, key=f"prop_{i}")
            with col_c2:
                # Campo editable para la decisión humana
                st.text_input(f"Tu Decisión Final ({i})", value=item['token_destino_propuesto'], key=f"dec_{i}")
            
            st.divider()

        # Botones de acción
        col_submit1, col_submit2 = st.columns([1, 4])
        with col_submit1:
            if st.form_submit_button("✅ APROBAR Y SELLAR", type="primary"):
                # Procesar decisiones
                for i, item in enumerate(items_a_revisar):
                    # Recuperar el valor del input con la key dinámica
                    valor_final = st.session_state.get(f"dec_{i}", item['token_destino_propuesto'])
                    
                    # Actualizar en Glosario
                    registrar_en_glosario(item['token_origen'], valor_final, item['categoria'])
                    
                    # Actualizar en los datos temporales para el renderizado final
                    # (Buscamos el item original en la lista completa por referencia)
                    item['token_destino_propuesto'] = valor_final
                    item['estado'] = "OK" # Ya resuelto
                
                st.session_state.estado_actual = "FINALIZADO"
                st.rerun()

# --- FASE 3: RESULTADO FINAL ---
elif st.session_state.estado_actual == "FINALIZADO":
    st.markdown("### 3. Traducción Final (Isomórfica)")
    
    datos = st.session_state.datos_temporales
    
    # Reconstrucción del texto a partir de los tokens procesados
    # Esto asegura que lo que ves es exactamente lo que se analizó + tus correcciones
    tokens_finales = [item["token_destino_propuesto"] for item in datos["analisis"]]
    texto_final = " ".join(tokens_finales)
    
    st.success(texto_final)
    
    # Visualización detallada
    with st.expander("🔍 Ver Matriz de Análisis Detallada"):
        df = pd.DataFrame(datos["analisis"])
        st.dataframe(df, use_container_width=True)

    st.divider()
    
    col_fin1, col_fin2, col_fin3 = st.columns([1, 1, 3])
    with col_fin1:
        if st.button("🔄 Traducir Otro Texto"):
            st.session_state.estado_actual = "ESPERANDO_INPUT"
            st.session_state.datos_temporales = None
            st.rerun()
            
    with col_fin2:
        st.download_button(
            label="📄 Descargar TXT",
            data=texto_final,
            file_name="traduccion_isomorfica.txt",
            mime="text/plain"
        )
