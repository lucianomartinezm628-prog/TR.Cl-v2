import streamlit as st
import google.generativeai as genai
import json
import pandas as pd
from datetime import datetime

# --- 1. CONFIGURACIÓN Y ESTILOS ---
st.set_page_config(layout="wide", page_title="Sistema de Traducción Isomórfica", page_icon="🛡️")

st.markdown("""
<style>
    .stTextArea textarea { font-family: 'Courier New', monospace; }
    .status-box { padding: 10px; border-radius: 5px; margin-bottom: 10px; }
    .status-ok { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
    .status-alert { background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
    .token-tag { background-color: #e2e6ea; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; border: 1px solid #ccc; margin-right: 4px; }
</style>
""", unsafe_allow_html=True)

# --- 2. GESTIÓN DE ESTADO (PERSISTENCIA TEMPORAL) ---
if "glosario" not in st.session_state:
    # Estructura: { "token_origen": { "target": "traducción", "tipo": "NUCLEO/PARTICULA", "locked": True/False } }
    st.session_state.glosario = {} 

if "historial_chat" not in st.session_state:
    st.session_state.historial_chat = []

if "estado_actual" not in st.session_state:
    st.session_state.estado_actual = "ESPERANDO_INPUT" # ESPERANDO_INPUT, PROCESANDO, CUSTODIA, FINALIZADO

if "datos_temporales" not in st.session_state:
    st.session_state.datos_temporales = None

# --- 3. DEFINICIÓN DEL SISTEMA (LA CONSTITUCIÓN PARA GEMINI) ---
SYSTEM_INSTRUCTION = """
ERES EL MOTOR DE PROCESAMIENTO DE UN SISTEMA DE TRADUCCIÓN ISOMÓRFICA.
TU OBJETIVO NO ES SER AMABLE, SINO CUMPLIR ESTRICTAMENTE LOS PROTOCOLOS P1-P11.

--- PROTOCOLOS FUNDAMENTALES ---

P1 (ISOMORFISMO): La traducción debe mantener una correspondencia 1:1 estricta en la medida de lo posible.
P2 (AUTORIDAD): El Usuario (P0) es la máxima autoridad. Ante duda (C1-C6), PREGUNTAR.
P4 (NÚCLEOS): Sustantivos, Verbos, Adjetivos son INVARIABLES una vez fijados en el Glosario.
    - Prioridad: Etimología > Uso Técnico.
    - Si no existe raíz en español: Usar Transliteración + Sufijo (Neologismo P9).
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
      "razonamiento": "Explicación breve (etimología/regla)",
      "estado": "OK" | "CONFLICTO" | "NUEVO",
      "duda_tipo": "C1...C6" (solo si estado es CONFLICTO)
    }
  ],
  "traduccion_borrador": "La frase completa traducida preliminarmente",
  "requiere_custodia": true | false
}

SIEMPRE que detectes una palabra nueva que sea un NÚCLEO, o una ambigüedad grave, marca "requiere_custodia": true y define el "estado" como "NUEVO" o "CONFLICTO".
"""

# --- 4. FUNCIONES DEL NÚCLEO ---

def obtener_glosario_texto():
    """Convierte el glosario Python a texto para el prompt de Gemini"""
    if not st.session_state.glosario:
        return "GLOSARIO VACÍO."
    texto = "GLOSARIO ACTUAL (OBLIGATORIO RESPETAR):\n"
    for k, v in st.session_state.glosario.items():
        texto += f"- {k} -> {v['target']} ({v['tipo']})\n"
    return texto

def consultar_gemini(prompt_usuario, api_key, modelo):
    """Envía la instrucción a Gemini con el contexto del Glosario"""
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=modelo,
            system_instruction=SYSTEM_INSTRUCTION,
            generation_config={"response_mime_type": "application/json"} # Forzamos JSON
        )
        
        # Inyectamos el glosario actual en el prompt
        prompt_completo = f"""
        {obtener_glosario_texto()}
        
        INPUT DEL USUARIO (TEXTO FUENTE):
        "{prompt_usuario}"
        
        Analiza token por token. Verifica contra el glosario. Genera el JSON.
        """
        
        with st.spinner('Gemini operando Protocolos P1-P10...'):
            response = model.generate_content(prompt_completo)
            return json.loads(response.text)
            
    except Exception as e:
        st.error(f"Error Crítico del Sistema: {str(e)}")
        return None

def actualizar_glosario(token, traduccion, tipo):
    """P8: Registro en Glosario"""
    st.session_state.glosario[token] = {
        "target": traduccion,
        "tipo": tipo,
        "fecha": datetime.now().strftime("%Y-%m-%d")
    }

# --- 5. INTERFAZ DE USUARIO ---

# Sidebar: Configuración
with st.sidebar:
    st.header("⚙️ Sala de Máquinas")
    
    api_key = st.text_input("Gemini API Key", type="password")
    
    modelo = st.selectbox("Modelo Activo", [
        "gemini-1.5-flash", # Recomendado por velocidad/costo
        "gemini-2.0-flash",
        "gemini-1.5-pro",
    ], index=0)
    
    st.divider()
    
    st.subheader("📚 Glosario (P8)")
    if st.session_state.glosario:
        df_glosario = pd.DataFrame.from_dict(st.session_state.glosario, orient='index')
        st.dataframe(df_glosario, use_container_width=True)
        
        if st.button("Exportar Glosario (JSON)"):
            st.json(st.session_state.glosario)
        
        if st.button("🗑️ Borrar Glosario (Reinicio)"):
            st.session_state.glosario = {}
            st.rerun()
    else:
        st.info("Glosario vacío.")

# Main: Panel de Control
st.title("🛡️ Sistema de Traducción Isomórfica")
st.caption("P0: Usuario = Autoridad Máxima. Gemini = Operador de Protocolos.")

# MODO: ESPERANDO INPUT
if st.session_state.estado_actual == "ESPERANDO_INPUT":
    texto_input = st.text_area("Texto Fuente (Árabe/Técnico)", height=150, placeholder="Escribe aquí el texto a procesar...")
    
    if st.button("Iniciar Procesamiento (P10.A)", type="primary"):
        if not api_key:
            st.error("Falta API Key")
        elif not texto_input:
            st.warning("Texto vacío")
        else:
            respuesta_json = consultar_gemini(texto_input, api_key, modelo)
            
            if respuesta_json:
                st.session_state.datos_temporales = respuesta_json
                
                # Determinamos flujo según si requiere custodia
                if respuesta_json.get("requiere_custodia"):
                    st.session_state.estado_actual = "CUSTODIA"
                else:
                    # Si no requiere custodia, auto-guardamos lo nuevo y finalizamos
                    for item in respuesta_json["analisis"]:
                        if item["estado"] == "NUEVO":
                            actualizar_glosario(item["token_origen"], item["token_destino_propuesto"], item["categoria"])
                    st.session_state.estado_actual = "FINALIZADO"
                
                st.rerun()

# MODO: CUSTODIA (HUMAN IN THE LOOP)
elif st.session_state.estado_actual == "CUSTODIA":
    st.markdown("### ⚠️ Panel de Custodia (P0)")
    st.info("Gemini ha detectado elementos nuevos o conflictos que requieren tu aprobación.")
    
    datos = st.session_state.datos_temporales
    analisis = datos["analisis"]
    
    with st.form("form_custodia"):
        conflictos_existentes = False
        
        for i, item in enumerate(analisis):
            # Solo mostramos items que requieren atención (Nuevos o Conflictos)
            if item["estado"] in ["NUEVO", "CONFLICTO"]:
                conflictos_existentes = True
                col1, col2, col3 = st.columns([1, 2, 2])
                
                with col1:
                    st.markdown(f"**{item['token_origen']}**")
                    st.caption(item['categoria'])
                
                with col2:
                    st.markdown(f"IA Propone: `{item['token_destino_propuesto']}`")
                    st.caption(f"Motivo: {item['razonamiento']}")
                
                with col3:
                    # Opciones de decisión
                    opcion = st.radio(
                        f"Decisión para '{item['token_origen']}':",
                        ["Aceptar Propuesta", "Editar Manualmente", "Ignorar (No guardar)"],
                        key=f"dec_{i}",
                        horizontal=True
                    )
                    
                    if opcion == "Editar Manualmente":
                        st.text_input(f"Corrección para {item['token_origen']}", key=f"manual_{i}")

        st.divider()
        submitted = st.form_submit_button("✅ Sellar Decisiones y Actualizar Glosario")
        
        if submitted:
            # Procesar el formulario
            for i, item in enumerate(analisis):
                if item["estado"] in ["NUEVO", "CONFLICTO"]:
                    decision = st.session_state[f"dec_{i}"]
                    
                    token_final = item['token_destino_propuesto']
                    guardar = False
                    
                    if decision == "Aceptar Propuesta":
                        guardar = True
                    elif decision == "Editar Manualmente":
                        token_final = st.session_state[f"manual_{i}"]
                        guardar = True
                    
                    if guardar:
                        actualizar_glosario(item['token_origen'], token_final, item['categoria'])
                        # Actualizamos el dato temporal para el renderizado final
                        st.session_state.datos_temporales["analisis"][i]["token_destino_propuesto"] = token_final
            
            st.session_state.estado_actual = "FINALIZADO"
            st.rerun()

# MODO: FINALIZADO
elif st.session_state.estado_actual == "FINALIZADO":
    st.markdown("### ✅ Resultado Final (P10.B)")
    
    datos = st.session_state.datos_temporales
    
    # Reconstrucción del texto final (Isomórfico)
    palabras_finales = [item["token_destino_propuesto"] for item in datos["analisis"]]
    texto_reconstruido = " ".join(palabras_finales)
    
    st.success(texto_reconstruido)
    
    with st.expander("Ver Matriz Isomórfica (Detalle)"):
        df_analisis = pd.DataFrame(datos["analisis"])
        st.table(df_analisis[["token_origen", "token_destino_propuesto", "categoria", "razonamiento"]])

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 Traducir Nuevo Texto"):
            st.session_state.estado_actual = "ESPERANDO_INPUT"
            st.session_state.datos_temporales = None
            st.rerun()
    with col2:
        st.download_button("Descargar Traducción", texto_reconstruido, file_name="traduccion.txt")

# --- PIE DE PÁGINA ---
st.divider()
if st.checkbox("Mostrar Logs del Sistema"):
    st.json(st.session_state.datos_temporales)
