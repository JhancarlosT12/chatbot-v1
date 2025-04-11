# app.py
from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import os
import uuid
import shutil
import json
import httpx
from PyPDF2 import PdfReader
import docx
import re

# Configuración
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "your_deepseek_api_key_here")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

app = FastAPI(title="Chatbot de Documentos Inteligente")

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Crear directorios necesarios
os.makedirs("uploads", exist_ok=True)
os.makedirs("static", exist_ok=True)
os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)

# Servir archivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")

# Almacenamiento en memoria para documentos y configuraciones de chatbots
documents = {}
chatbots = {}

# Modelos de datos
class Question(BaseModel):
    question: str
    document_id: str
    chat_history: list = []

class ChatbotConfig(BaseModel):
    name: str
    document_id: str
    primary_color: str = "#007bff"
    bubble_icon: str = "chat"
    welcome_message: str = "Hola, ¿en qué puedo ayudarte sobre este documento?"
    placeholder_text: str = "Escribe tu pregunta aquí..."

# Extraer texto de diferentes tipos de documentos
def extract_text(file_path):
    _, extension = os.path.splitext(file_path)
    
    if extension.lower() == '.pdf':
        text = ""
        with open(file_path, 'rb') as f:
            pdf = PdfReader(f)
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text
    
    elif extension.lower() == '.docx':
        doc = docx.Document(file_path)
        return "\n".join([paragraph.text for paragraph in doc.paragraphs if paragraph.text])
    
    elif extension.lower() in ['.txt', '.csv', '.md']:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    
    else:
        raise ValueError(f"Formato de archivo no soportado: {extension}")

# Procesar texto para chunking y mejor procesamiento
def process_text(text):
    # Eliminar espacios en blanco excesivos y líneas vacías
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

# Chunking del texto para procesamiento eficiente
def chunk_text(text, chunk_size=1000, overlap=100):
    processed_text = process_text(text)
    chunks = []
    
    if len(processed_text) <= chunk_size:
        chunks.append(processed_text)
    else:
        start = 0
        while start < len(processed_text):
            end = min(start + chunk_size, len(processed_text))
            
            # Ajustar final para no cortar en medio de una palabra
            if end < len(processed_text):
                while end > start and processed_text[end] != ' ':
                    end -= 1
            
            chunks.append(processed_text[start:end])
            start = end - overlap
    
    return chunks

# Función para consultar a la API de Deepseek
async def query_deepseek(question, document_text, chat_history=[]):
    # Preparar el contexto del documento
    chunks = chunk_text(document_text)
    context = "\n\n".join(chunks[:3])  # Usar los primeros chunks para el contexto
    
    # Construir el historial de chat formateado
    formatted_history = []
    for entry in chat_history[-5:]:  # Usar últimas 5 entradas para mantener contexto manejable
        formatted_history.append({"role": "user", "content": entry["question"]})
        formatted_history.append({"role": "assistant", "content": entry["answer"]})
    
    # Crear el mensaje para la API
    messages = [
        {"role": "system", "content": "Eres un asistente útil que responde preguntas basándose en la información proporcionada en el documento. Responde de manera concisa y precisa basándote solo en la información del documento. Si la respuesta no se encuentra en el documento, indícalo claramente."},
        {"role": "user", "content": f"Documento:\n\n{context}\n\nPregunta: {question}"}
    ]
    
    # Insertar historial si existe
    if formatted_history:
        messages = [messages[0]] + formatted_history + [messages[1]]
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                DEEPSEEK_API_URL,
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "deepseek-chat",
                    "messages": messages,
                    "temperature": 0.1,  # Baja temperatura para respuestas más precisas
                    "max_tokens": 500
                }
            )
            
            result = response.json()
            
            if "choices" in result and len(result["choices"]) > 0:
                return result["choices"][0]["message"]["content"]
            else:
                raise ValueError("No se recibió una respuesta válida de Deepseek")
                
    except Exception as e:
        print(f"Error al consultar Deepseek: {str(e)}")
        return f"Lo siento, hubo un problema al procesar tu pregunta. Error: {str(e)}"

# Página principal con HTML básico 
@app.get("/", response_class=HTMLResponse)
async def get_home():
    # Leeremos el HTML desde un archivo estático más adelante
    # Por ahora, devolvemos una página simple con redirección al dashboard
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>DocumentChat - Chatbots inteligentes para tus documentos</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="stylesheet" href="/static/css/main.css">
    </head>
    <body>
        <div class="container py-5">
            <div class="text-center mb-5">
                <h1 class="display-4">DocumentChat</h1>
                <p class="lead">Crea chatbots inteligentes a partir de tus documentos</p>
                <a href="/dashboard" class="btn btn-primary btn-lg mt-3">Ir al Dashboard</a>
            </div>
        </div>
    </body>
    </html>
    """

# Dashboard para gestionar chatbots
@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Dashboard - DocumentChat</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
        <link rel="stylesheet" href="/static/css/dashboard.css">
    </head>
    <body>
        <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
            <div class="container">
                <a class="navbar-brand" href="/">DocumentChat</a>
                <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                    <span class="navbar-toggler-icon"></span>
                </button>
                <div class="collapse navbar-collapse" id="navbarNav">
                    <ul class="navbar-nav ms-auto">
                        <li class="nav-item">
                            <a class="nav-link active" href="/dashboard">Dashboard</a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="/settings">Configuración</a>
                        </li>
                    </ul>
                </div>
            </div>
        </nav>

        <div class="container py-4">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h1>Mis Chatbots</h1>
                <button id="createNewBtn" class="btn btn-primary">
                    <i class="bi bi-plus-lg"></i> Crear nuevo chatbot
                </button>
            </div>

            <div class="row" id="chatbotsList">
                <!-- Los chatbots se cargarán aquí dinámicamente -->
            </div>

            <!-- Modal para crear/editar chatbot -->
            <div class="modal fade" id="chatbotModal" tabindex="-1">
                <div class="modal-dialog modal-lg">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title" id="modalTitle">Crear nuevo chatbot</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <form id="chatbotForm">
                                <div class="mb-3">
                                    <label for="chatbotName" class="form-label">Nombre del chatbot</label>
                                    <input type="text" class="form-control" id="chatbotName" required>
                                </div>
                                <div class="mb-3">
                                    <label for="document" class="form-label">Documento (.pdf, .docx, .txt)</label>
                                    <input type="file" class="form-control" id="document" accept=".pdf,.docx,.txt">
                                </div>
                                <div class="mb-3">
                                    <label for="primaryColor" class="form-label">Color primario</label>
                                    <input type="color" class="form-control form-control-color" id="primaryColor" value="#007bff">
                                </div>
                                <div class="mb-3">
                                    <label for="welcomeMessage" class="form-label">Mensaje de bienvenida</label>
                                    <textarea class="form-control" id="welcomeMessage" rows="2">Hola, ¿en qué puedo ayudarte sobre este documento?</textarea>
                                </div>
                                <div class="mb-3">
                                    <label for="placeholderText" class="form-label">Texto del placeholder</label>
                                    <input type="text" class="form-control" id="placeholderText" value="Escribe tu pregunta aquí...">
                                </div>
                                <input type="hidden" id="chatbotId">
                            </form>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
                            <button type="button" class="btn btn-primary" id="saveChatbotBtn">Guardar</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"></script>
        <script src="/static/js/dashboard.js"></script>
    </body>
    </html>
    """

# Ruta para obtener la lista de chatbots
@app.get("/api/chatbots")
async def get_chatbots():
    chatbots_list = []
    for chatbot_id, config in chatbots.items():
        chatbots_list.append({
            "id": chatbot_id,
            "name": config["name"],
            "document_name": documents[config["document_id"]]["filename"] if config["document_id"] in documents else "Unknown",
            "primary_color": config["primary_color"],
            "created_at": config.get("created_at", "")
        })
    return chatbots_list

# Ruta para subir documentos
@app.post("/api/upload-document/")
async def upload_document(document: UploadFile = File(...)):
    # Generar ID único para el documento
    document_id = str(uuid.uuid4())
    
    # Crear directorio para guardar el archivo
    file_path = f"uploads/{document_id}_{document.filename}"
    
    try:
        # Guardar el archivo
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(document.file, buffer)
        
        # Extraer texto del documento
        try:
            document_text = extract_text(file_path)
            document_text = process_text(document_text)
            
            # Almacenar el texto
            documents[document_id] = {
                "filename": document.filename,
                "path": file_path,
                "text": document_text
            }
            
            return {"document_id": document_id, "filename": document.filename}
        
        except Exception as e:
            os.remove(file_path)  # Eliminar archivo si hay error
            raise HTTPException(status_code=400, detail=f"Error al procesar el documento: {str(e)}")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al subir el documento: {str(e)}")

# Ruta para crear un nuevo chatbot
@app.post("/api/chatbots/")
async def create_chatbot(config: ChatbotConfig):
    chatbot_id = str(uuid.uuid4())
    
    # Verificar que el documento existe
    if config.document_id not in documents:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    
    # Guardar la configuración del chatbot
    chatbots[chatbot_id] = {
        "name": config.name,
        "document_id": config.document_id,
        "primary_color": config.primary_color,
        "bubble_icon": config.bubble_icon,
        "welcome_message": config.welcome_message,
        "placeholder_text": config.placeholder_text,
        "created_at": "2025-04-11" # En producción usaríamos datetime.now().isoformat()
    }
    
    return {"chatbot_id": chatbot_id}

# Ruta para obtener un chatbot específico
@app.get("/api/chatbots/{chatbot_id}")
async def get_chatbot(chatbot_id: str):
    if chatbot_id not in chatbots:
        raise HTTPException(status_code=404, detail="Chatbot no encontrado")
    
    config = chatbots[chatbot_id]
    document_info = {"filename": "Unknown"}
    
    if config["document_id"] in documents:
        document_info = {"filename": documents[config["document_id"]]["filename"]}
    
    return {
        "id": chatbot_id,
        "name": config["name"],
        "document_id": config["document_id"],
        "document_info": document_info,
        "primary_color": config["primary_color"],
        "bubble_icon": config["bubble_icon"],
        "welcome_message": config["welcome_message"],
        "placeholder_text": config["placeholder_text"]
    }

# Ruta para actualizar un chatbot
@app.put("/api/chatbots/{chatbot_id}")
async def update_chatbot(chatbot_id: str, config: ChatbotConfig):
    if chatbot_id not in chatbots:
        raise HTTPException(status_code=404, detail="Chatbot no encontrado")
    
    # Verificar que el documento existe
    if config.document_id not in documents:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    
    # Actualizar la configuración
    chatbots[chatbot_id].update({
        "name": config.name,
        "document_id": config.document_id,
        "primary_color": config.primary_color,
        "bubble_icon": config.bubble_icon,
        "welcome_message": config.welcome_message,
        "placeholder_text": config.placeholder_text
    })
    
    return {"message": "Chatbot actualizado correctamente"}

# Ruta para eliminar un chatbot
@app.delete("/api/chatbots/{chatbot_id}")
async def delete_chatbot(chatbot_id: str):
    if chatbot_id not in chatbots:
        raise HTTPException(status_code=404, detail="Chatbot no encontrado")
    
    del chatbots[chatbot_id]
    return {"message": "Chatbot eliminado correctamente"}

# Ruta para hacer preguntas al chatbot
@app.post("/api/ask-question/")
async def ask_question(question_data: Question):
    document_id = question_data.document_id
    question = question_data.question
    chat_history = question_data.chat_history
    
    if document_id not in documents:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    
    try:
        # Obtener el texto del documento
        document_text = documents[document_id]["text"]
        
        # Consultar a la API de Deepseek
        answer = await query_deepseek(question, document_text, chat_history)
        
        return {"answer": answer}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar la pregunta: {str(e)}")

# Widget JavaScript para incrustar en sitios web
@app.get("/api/widget/{chatbot_id}.js")
async def get_widget_script(chatbot_id: str):
    if chatbot_id not in chatbots:
        raise HTTPException(status_code=404, detail="Chatbot no encontrado")
    
    config = chatbots[chatbot_id]
    
    # Generar script personalizado para el chatbot
    script = f"""
    // DocumentChat Widget v1.0
    (function() {{
        const chatbotId = "{chatbot_id}";
        const primaryColor = "{config['primary_color']}";
        const welcomeMessage = "{config['welcome_message']}";
        const placeholderText = "{config['placeholder_text']}";
        
        // Crear estilos
        const style = document.createElement('style');
        style.innerHTML = `
            .dc-widget-container {{
                position: fixed;
                bottom: 20px;
                right: 20px;
                z-index: 9999;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', sans-serif;
            }}
            .dc-chat-button {{
                width: 60px;
                height: 60px;
                border-radius: 50%;
                background-color: {config['primary_color']};
                color: white;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                box-shadow: 0 2px 12px rgba(0, 0, 0, 0.15);
                transition: all 0.3s ease;
            }}
            .dc-chat-button:hover {{
                transform: scale(1.05);
            }}
            .dc-chat-window {{
                display: none;
                position: fixed;
                bottom: 90px;
                right: 20px;
                width: 350px;
                height: 500px;
                background-color: white;
                border-radius: 12px;
                overflow: hidden;
                box-shadow: 0 5px 25px rgba(0, 0, 0, 0.15);
                flex-direction: column;
            }}
            .dc-chat-header {{
                background-color: {config['primary_color']};
                color: white;
                padding: 15px;
                font-weight: 500;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }}
            .dc-chat-close {{
                cursor: pointer;
                opacity: 0.8;
            }}
            .dc-chat-close:hover {{
                opacity: 1;
            }}
            .dc-chat-messages {{
                flex: 1;
                padding: 15px;
                overflow-y: auto;
            }}
            .dc-message {{
                margin-bottom: 10px;
                max-width: 80%;
                padding: 10px 14px;
                border-radius: 18px;
                line-height: 1.4;
                word-wrap: break-word;
                position: relative;
            }}
            .dc-bot-message {{
                background-color: #f1f1f1;
                color: #333;
                border-top-left-radius: 4px;
                margin-right: auto;
            }}
            .dc-user-message {{
                background-color: {config['primary_color']};
                color: white;
                border-top-right-radius: 4px;
                margin-left: auto;
            }}
            .dc-chat-input-container {{
                border-top: 1px solid #eaeaea;
                padding: 12px;
                display: flex;
            }}
            .dc-chat-input {{
                flex: 1;
                padding: 10px 14px;
                border: 1px solid #ddd;
                border-radius: 20px;
                outline: none;
                font-size: 14px;
            }}
            .dc-chat-input:focus {{
                border-color: {config['primary_color']};
            }}
            .dc-send-button {{
                margin-left: 8px;
                width: 36px;
                height: 36px;
                border-radius: 50%;
                background-color: {config['primary_color']};
                color: white;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                border: none;
            }}
            .dc-send-button:disabled {{
                opacity: 0.5;
                cursor: not-allowed;
            }}
            .dc-loading {{
                display: flex;
                padding: 10px;
                align-items: center;
            }}
            .dc-loading-dots {{
                display: flex;
            }}
            .dc-loading-dots span {{
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background-color: #888;
                margin: 0 2px;
                animation: dc-loading 1.4s infinite ease-in-out both;
            }}
            .dc-loading-dots span:nth-child(1) {{
                animation-delay: -0.32s;
            }}
            .dc-loading-dots span:nth-child(2) {{
                animation-delay: -0.16s;
            }}
            @keyframes dc-loading {{
                0%, 80%, 100% {{ transform: scale(0); }}
                40% {{ transform: scale(1); }}
            }}
        `;
        document.head.appendChild(style);
        
        // Crear el HTML del widget
        const container = document.createElement('div');
        container.className = 'dc-widget-container';
        
        // Botón de chat
        const chatButton = document.createElement('div');
        chatButton.className = 'dc-chat-button';
        chatButton.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>';
        container.appendChild(chatButton);
        
        // Ventana de chat
        const chatWindow = document.createElement('div');
        chatWindow.className = 'dc-chat-window';
        
        // Encabezado
        const chatHeader = document.createElement('div');
        chatHeader.className = 'dc-chat-header';
        chatHeader.innerHTML = `
            <div>DocumentChat</div>
            <div class="dc-chat-close">✕</div>
        `;
        chatWindow.appendChild(chatHeader);
        
        // Contenedor de mensajes
        const messagesContainer = document.createElement('div');
        messagesContainer.className = 'dc-chat-messages';
        chatWindow.appendChild(messagesContainer);
        
        // Contenedor de entrada
        const inputContainer = document.createElement('div');
        inputContainer.className = 'dc-chat-input-container';
        inputContainer.innerHTML = `
            <input type="text" class="dc-chat-input" placeholder="${placeholderText}">
            <button class="dc-send-button" disabled>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="22" y1="2" x2="11" y2="13"></line>
                    <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                </svg>
            </button>
        `;
        chatWindow.appendChild(inputContainer);
        
        container.appendChild(chatWindow);
        document.body.appendChild(container);
        
        // Funcionalidad
        const chatInput = document.querySelector('.dc-chat-input');
        const sendButton = document.querySelector('.dc-send-button');
        let chatHistory = [];
        
        // Mensaje de bienvenida
        function addWelcomeMessage() {{
            const welcomeDiv = document.createElement('div');
            welcomeDiv.className = 'dc-message dc-bot-message';
            welcomeDiv.textContent = welcomeMessage;
            messagesContainer.appendChild(welcomeDiv);
        }}
        
        // Mostrar mensaje de carga
        function showLoading() {{
            const loadingDiv = document.createElement('div');
            loadingDiv.className = 'dc-message dc-bot-message dc-loading';
            loadingDiv.innerHTML = `
                <div class="dc-loading-dots">
                    <span></span>
                    <span></span>
                    <span></span>
                </div>
            `;
            loadingDiv.id = 'dc-loading-indicator';
            messagesContainer.appendChild(loadingDiv);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }}
        
        // Ocultar mensaje de carga
        function hideLoading() {{
            const loadingDiv = document.getElementById('dc-loading-indicator');
            if (loadingDiv) {{
                loadingDiv.remove();
            }}
        }}
        
        // Añadir un mensaje al chat
        function addMessage(content, isUser = false) {{
            const messageDiv = document.createElement('div');
            messageDiv.className = isUser ? 'dc-message dc-user-message' : 'dc-message dc-bot-message';
            messageDiv.textContent = content;
            messagesContainer.appendChild(messageDiv);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }}
        
        // Enviar pregunta al servidor
        async function sendQuestion(question) {{
            try {{
                showLoading();
                
                const response = await fetch('{os.environ.get("BASE_URL", "https://your-app-url.com")}/api/ask-question/', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                    }},
                    body: JSON.stringify({{
                        question: question,
                        document_id: "{config['document_id']}",
                        chat_history: chatHistory
                    }})
                }});
                
                hideLoading();
                
                if (response.ok) {{
                    const data = await response.json();
                    addMessage(data.answer);
                    
                    // Añadir a historial
                    chatHistory.push({{
                        question: question,
                        answer: data.answer
                    }});
                    
                    // Mantener historial manejable
                    if (chatHistory.length > 10) {{
                        chatHistory.shift();
                    }}
                }} else {{
                    const error = await response.json();
                    addMessage('Lo siento, hubo un problema al procesar tu pregunta.');
                    console.error('Error:', error);
                }}
            }} catch (error) {{
                hideLoading();
                addMessage('Lo siento, no pude conectarme con el servidor. Por favor intenta de nuevo más tarde.');
                console.error('Error:', error);
            }}
        }}
        
        // Event listeners
        chatButton.addEventListener('click', () => {{
            chatWindow.style.display = 'flex';
            chatButton.style.display = 'none';
            
            // Si no hay mensajes, añadir mensaje de bienvenida
            if (messagesContainer.children.length === 0) {{
                addWelcomeMessage();
            }}
            
            chatInput.focus();
        }});document.querySelector('.dc-chat-close').addEventListener('click', () => {
            chatWindow.style.display = 'none';
            chatButton.style.display = 'flex';
        });
        
        chatInput.addEventListener('input', () => {
            sendButton.disabled = chatInput.value.trim() === '';
        });
        
        chatInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && chatInput.value.trim() !== '') {
                const question = chatInput.value.trim();
                addMessage(question, true);
                chatInput.value = '';
                sendButton.disabled = true;
                sendQuestion(question);
            }
        });
        
        sendButton.addEventListener('click', () => {
            if (chatInput.value.trim() !== '') {
                const question = chatInput.value.trim();
                addMessage(question, true);
                chatInput.value = '';
                sendButton.disabled = true;
                sendQuestion(question);
            }
        });
    }})();
    """
    
    return Response(content=script, media_type="application/javascript")

# Ruta para obtener el código de integración del widget
@app.get("/api/chatbots/{chatbot_id}/embed")
async def get_embed_code(chatbot_id: str, request: Request):
    if chatbot_id not in chatbots:
        raise HTTPException(status_code=404, detail="Chatbot no encontrado")
    
    # Obtener la URL base de la solicitud
    base_url = str(request.base_url).rstrip('/')
    
    # Generar el código de integración
    embed_code = f"""
    <!-- DocumentChat Widget -->
    <script src="{base_url}/api/widget/{chatbot_id}.js" async></script>
    """
    
    return {"embed_code": embed_code}

# Ruta para la página del chat directo
@app.get("/chat/{chatbot_id}", response_class=HTMLResponse)
async def get_chat_page(chatbot_id: str):
    if chatbot_id not in chatbots:
        raise HTTPException(status_code=404, detail="Chatbot no encontrado")
    
    config = chatbots[chatbot_id]
    
    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{config['name']} - DocumentChat</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body {{ 
                display: flex;
                flex-direction: column;
                height: 100vh;
                background-color: #f8f9fa;
            }}
            .chat-container {{
                flex: 1;
                display: flex;
                flex-direction: column;
                background-color: white;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                overflow: hidden;
            }}
            .chat-header {{
                padding: 15px 20px;
                background-color: {config['primary_color']};
                color: white;
                font-weight: 500;
            }}
            .chat-messages {{
                flex: 1;
                padding: 20px;
                overflow-y: auto;
            }}
            .message {{
                margin-bottom: 15px;
                max-width: 80%;
                padding: 10px 15px;
                border-radius: 18px;
                line-height: 1.4;
                word-wrap: break-word;
            }}
            .bot-message {{
                background-color: #f1f1f1;
                color: #333;
                border-top-left-radius: 4px;
                margin-right: auto;
            }}
            .user-message {{
                background-color: {config['primary_color']};
                color: white;
                border-top-right-radius: 4px;
                margin-left: auto;
            }}
            .chat-input-container {{
                padding: 15px;
                border-top: 1px solid #eaeaea;
                background-color: white;
            }}
            .chat-input-container form {{
                display: flex;
            }}
            .chat-input {{
                flex: 1;
                padding: 12px 15px;
                border: 1px solid #ddd;
                border-radius: 24px;
                outline: none;
            }}
            .chat-input:focus {{
                border-color: {config['primary_color']};
            }}
            .send-button {{
                margin-left: 10px;
                border: none;
                background-color: {config['primary_color']};
                color: white;
                border-radius: 50%;
                width: 46px;
                height: 46px;
                display: flex;
                align-items: center;
                justify-content: center;
            }}
            .send-button:disabled {{
                opacity: 0.5;
            }}
            .loading-indicator {{
                display: flex;
                padding: 10px;
            }}
            .loading-dots {{
                display: flex;
            }}
            .loading-dots span {{
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background-color: #888;
                margin: 0 2px;
                animation: loading 1.4s infinite ease-in-out both;
            }}
            .loading-dots span:nth-child(1) {{
                animation-delay: -0.32s;
            }}
            .loading-dots span:nth-child(2) {{
                animation-delay: -0.16s;
            }}
            @keyframes loading {{
                0%, 80%, 100% {{ transform: scale(0); }}
                40% {{ transform: scale(1); }}
            }}
        </style>
    </head>
    <body>
        <div class="container py-4 h-100 d-flex flex-column">
            <h4 class="mb-4">{config['name']}</h4>
            
            <div class="chat-container">
                <div class="chat-header">
                    DocumentChat
                </div>
                
                <div class="chat-messages" id="chatMessages">
                    <div class="message bot-message">
                        {config['welcome_message']}
                    </div>
                </div>
                
                <div class="chat-input-container">
                    <form id="questionForm">
                        <input type="text" id="questionInput" class="chat-input" 
                               placeholder="{config['placeholder_text']}" autocomplete="off">
                        <button type="submit" id="sendButton" class="send-button" disabled>
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" 
                                 stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <line x1="22" y1="2" x2="11" y2="13"></line>
                                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                            </svg>
                        </button>
                    </form>
                </div>
            </div>
        </div>
        
        <script>
            const chatMessages = document.getElementById('chatMessages');
            const questionForm = document.getElementById('questionForm');
            const questionInput = document.getElementById('questionInput');
            const sendButton = document.getElementById('sendButton');
            let chatHistory = [];
            
            // Habilitar/deshabilitar botón de envío
            questionInput.addEventListener('input', () => {{
                sendButton.disabled = questionInput.value.trim() === '';
            }});
            
            // Mostrar indicador de carga
            function showLoading() {{
                const loadingDiv = document.createElement('div');
                loadingDiv.className = 'message bot-message loading-indicator';
                loadingDiv.id = 'loadingIndicator';
                loadingDiv.innerHTML = `
                    <div class="loading-dots">
                        <span></span>
                        <span></span>
                        <span></span>
                    </div>
                `;
                chatMessages.appendChild(loadingDiv);
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }}
            
            // Ocultar indicador de carga
            function hideLoading() {{
                const loadingDiv = document.getElementById('loadingIndicator');
                if (loadingDiv) {{
                    loadingDiv.remove();
                }}
            }}
            
            // Añadir mensaje al chat
            function addMessage(content, isUser = false) {{
                const messageDiv = document.createElement('div');
                messageDiv.className = isUser ? 'message user-message' : 'message bot-message';
                messageDiv.textContent = content;
                chatMessages.appendChild(messageDiv);
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }}
            
            // Enviar pregunta
            async function sendQuestion(question) {{
                try {{
                    showLoading();
                    
                    const response = await fetch('/api/ask-question/', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/json',
                        }},
                        body: JSON.stringify({{
                            question: question,
                            document_id: '{config['document_id']}',
                            chat_history: chatHistory
                        }})
                    }});
                    
                    hideLoading();
                    
                    if (response.ok) {{
                        const data = await response.json();
                        addMessage(data.answer);
                        
                        // Añadir a historial
                        chatHistory.push({{
                            question: question,
                            answer: data.answer
                        }});
                        
                        // Mantener historial manejable
                        if (chatHistory.length > 10) {{
                            chatHistory.shift();
                        }}
                    }} else {{
                        const error = await response.json();
                        addMessage('Lo siento, hubo un problema al procesar tu pregunta.');
                        console.error('Error:', error);
                    }}
                }} catch (error) {{
                    hideLoading();
                    addMessage('Lo siento, no pude conectarme con el servidor.');
                    console.error('Error:', error);
                }}
            }}
            
            // Manejar envío del formulario
            questionForm.addEventListener('submit', (e) => {{
                e.preventDefault();
                
                const question = questionInput.value.trim();
                if (question !== '') {{
                    addMessage(question, true);
                    questionInput.value = '';
                    sendButton.disabled = true;
                    sendQuestion(question);
                }}
            }});
        </script>
    </body>
    </html>
    """

# Punto de entrada para ejecutar la aplicación
if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
