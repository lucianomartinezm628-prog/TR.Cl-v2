import streamlit as st
import google.generativeai as genai
import json
import pandas as pd
import time
from datetime import datetime

# --- 1. CONFIGURACIÓN Y ESTILOS ---
st.set_page_config(layout="wide", page_title="Sistema de Traducción Isomórfica", page_icon="🛡️")

st.markdown("""
<style>
    .stTextArea textarea { font-family: 'Courier New', monospace; }
    .status-box { padding: 10px; border-radius: 5px; margin-bottom: 10px; }
    .token-tag { background-color: #e2e6ea; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; border: 1px solid #ccc; margin-right: 4px; }
</style>
""", unsafe_allow_html=True)

# --- 2. GESTIÓN DE ESTADO ---
if "glosario" not in st.session_state:
    st.session_state.glosario = {} 

if "estado_actual" not in st.session_state:
    st.session_state.estado_actual = "ESPERANDO_INPUT"

if "datos_temporales" not in st.session_state:
    st.session_state.datos_temporales = None

# --- 3. CONSTITUCIÓN DEL SISTEMA (SYSTEM PROMPT) ---
SYSTEM_INSTRUCTION = """
ERES EL MOTOR DE PROCESAMIENTO DE UN SISTEMA DE TRADUCCIÓN ISOMÓRFICA.
TU OBJETIVO NO ES SER AMABLE, SINO CUMPLIR ESTRICTAMENTE LOS PROTOCOLOS P1-P11.

--- PROTOCOLOS FUNDAMENTALES ---
P1 (ISOMORFISMO): La traducción debe mantener una correspondencia 1:1 estricta en la medida de lo posible.
P2 (AUTORIDAD): El Usuario (P0) es la máxima autoridad. Ante duda (C1-C6), PREGUNTAR.
P4 (NÚCLEOS): Sustantivos, Verbos, Adjetivos son INVARIABLES una vez fijados en el Glosario.
    - Prioridad: Etimología > Uso Técnico.
    - Si no existe raíz en español: Usar Transliteración + Sufijo.
P5 (PARTÍCULAS): Preposiciones/Conjunciones son POLIVALENTES. Dependen de la función sintáctica.
P8 (GLOSARIO): 
    - Consultar SIEMPRE el glosario proporcionado.
    - Si el token está en el glosario, USAR esa traducción obligatoriamente.
    - Si el token es nuevo, proponer traducción basada en etimología.

--- INSTRUCCIONES DE SALIDA (FORMATO JSON) ---
NO respondas con texto plano. Responde SIEMPRE con un objeto JSON con esta estructura exacta:
{
  "analisis": [
    {
      "token_origen": "palabra_arabe",
      "token_destino_propuesto": "palabra_espanol",
      "categoria": "NUCLEO" | "PARTICULA" | "LOCUCION",
      "razonamiento": "Explicación breve",
      "estado": "OK" | "CONFLICTO" | "NUEVO"
    }
  ],
  "traduccion_borrador": "frase completa",
  "requiere_custodia": true | false
}
SI detectas una palabra nueva (NUCLEO) o ambigüedad, marca "requiere_custodia": true y estado "NUEVO" o "CONFLICTO".
"""

# --- 4. FUNCIONES DEL NÚCLEO (CON REINTENTO ANTI-ERROR 429) ---

def obtener_glosario_texto():
    if not st.session_state.glosario:
        return "GLOSARIO VACÍO."
    texto = "GLOSARIO ACTUAL (OBLIGATORIO RESPETAR):\n"
    for k, v in st.session_state.glosario.items():
        texto += f"- {k} -> {v['target']} ({v['tipo']})\n"
    return texto

def consultar_gemini(prompt_usuario, api_key, modelo):
    """
    Envía la instrucción a Gemini con sistema de reintento automático
    para evitar el error 429.
    """
    genai.configure(api_key=api_key)
    
    # Prompt completo con Glosario inyectado
    prompt_completo = f"""
    {obtener_glosario_texto()}
    
    INPUT DEL USUARIO (TEXTO FUENTE):
    "{prompt_usuario}"
    
    Analiza token por token. Verifica contra el glosario. Genera el JSON.
    """

    model = genai.GenerativeModel(
        model_name=modelo,
        system_instruction=SYSTEM_INSTRUCTION,
        generation_config={"response_mime_type": "application/json"}
    )

    # Lógica de Reintento (Backoff)
    max_reintentos = 3
    espera = 2 # segundos

    for intento in range(max_reintentos):
        try:
            with st.spinner(f'Gemini procesando (Intento {intento+1})...'):
                response = model.generate_content(prompt_completo)
                return json.loads(response.text)
        
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg:
                # Si es error de cuota, esperamos y reintentamos
                st.toast(f"⏳ Tráfico alto (429). Reintentando en {espera}s...", icon="⚠️")
                time.sleep(espera)
                espera *= 2 # Esperar el doble la próxima vez (2s, 4s, 8s)
                continue
            elif "404" in error_msg:
                st.error(f"❌ El modelo '{modelo}' no es compatible. Cambia el modelo en la barra lateral.")
                return None
            else:
                st.error(f"Error desconocido: {error_msg}")
                return None
    
    st.error("❌ El sistema está saturado. Intenta cambiar de modelo o espera un minuto.")
    return None

def actualizar_glosario(token, traduccion, tipo):
    st.session_state.glosario[token] = {
        "target": traduccion,
        "tipo": tipo,
        "fecha": datetime.now().strftime("%Y-%m-%d")
    }

# --- 5. INTERFAZ DE USUARIO ---

with st.sidebar:
    st.header("⚙️ Configuración")
    api_key = st.text_input("Gemini API Key", type="password")
    
    # LISTA DE MODELOS FILTRADA SEGÚN TU REGIÓN
    # Priorizamos los "Lite" y "Latest" para evitar el error 429
    modelos_usuario = [
        "gemini-flash-latest",       # La opción más segura (alias automático)
        "gemini-2.0-flash-lite",     # Rápido y ligero
        "gemini-2.5-flash-lite",     # Versión preview ligera
        "gemini-2.5-flash",          # Potente (puede dar error de cuota)
        "gemini-2.0-flash",          # Potente (puede dar error de cuota)
        "gemini-exp-1206"            # Experimental
    ]
    
    modelo = st.selectbox("Modelo Activo", modelos_usuario, index=0)
    st.caption("Nota: Si sale error 429, usa una versión 'Lite' o 'Latest'.")
    
    st.divider()
    st.subheader("📚 Glosario P8")
    if st.session_state.glosario:
        st.json(st.session_state.glosario)
        if st.button("Borrar Glosario"):
            st.session_state.glosario = {}
            st.rerun()

# --- PANEL PRINCIPAL ---
st.title("🛡️ Sistema de Traducción Isomórfica")

if st.session_state.estado_actual == "ESPERANDO_INPUT":
    texto_input = st.text_area("Texto Fuente", height=150)
    
    if st.button("🚀 Iniciar Protocolos", type="primary"):
        if not api_key:
            st.error("Falta API Key")
        elif not texto_input:
            st.warning("Escribe algo")
        else:
            respuesta = consultar_gemini(texto_input, api_key, modelo)
            if respuesta:
                st.session_state.datos_temporales = respuesta
                if respuesta.get("requiere_custodia"):
                    st.session_state.estado_actual = "CUSTODIA"
                else:
                    # Auto-guardar lo nuevo
                    for item in respuesta["analisis"]:
                        if item["estado"] == "NUEVO":
                            actualizar_glosario(item["token_origen"], item["token_destino_propuesto"], item["categoria"])
                    st.session_state.estado_actual = "FINALIZADO"
                st.rerun()

elif st.session_state.estado_actual == "CUSTODIA":
    st.warning("⚠️ Custodia Requerida (P0)")
    datos = st.session_state.datos_temporales
    
    with st.form("custodia_form"):
        for i, item in enumerate(datos["analisis"]):
            if item["estado"] in ["NUEVO", "CONFLICTO"]:
                col1, col2 = st.columns([1, 3])
                with col1:
                    st.markdown(f"**{item['token_origen']}**")
                    st.caption(item['categoria'])
                with col2:
                    val = st.text_input(f"Traducción ({item['razonamiento']})", 
                                  value=item['token_destino_propuesto'], 
                                  key=f"input_{i}")
        
        if st.form_submit_button("✅ Aprobar y Guardar"):
            # Guardar decisiones
            for i, item in enumerate(datos["analisis"]):
                if item["estado"] in ["NUEVO", "CONFLICTO"]:
                    key = f"input_{i}"
                    if key in st.session_state:
                        nuevo_valor = st.session_state[key]
                        actualizar_glosario(item['token_origen'], nuevo_valor, item['categoria'])
                        # Actualizar dato temporal para visualización
                        st.session_state.datos_temporales["analisis"][i]["token_destino_propuesto"] = nuevo_valor
            
            st.session_state.estado_actual = "FINALIZADO"
            st.rerun()

elif st.session_state.estado_actual == "FINALIZADO":
    st.success("✅ Procesamiento Completado")
    datos = st.session_state.datos_temporales
    
    # Reconstruir texto final
    final = " ".join([x["token_destino_propuesto"] for x in datos["analisis"]])
    st.markdown(f"### {final}")
    
    if st.button("Traducir otro texto"):
        st.session_state.estado_actual = "ESPERANDO_INPUT"
        st.session_state.datos_temporales = None
        st.rerun()
