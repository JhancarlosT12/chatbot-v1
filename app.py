# app.py
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn
import os
import uuid
import shutil
from PyPDF2 import PdfReader
import docx

app = FastAPI(title="Chatbot de Documentos Simple")

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Crear directorio para subidas
os.makedirs("uploads", exist_ok=True)

# Almacenamiento en memoria para documentos
documents = {}

# Modelo para preguntas
class Question(BaseModel):
    question: str
    document_id: str

# Extraer texto de diferentes tipos de documentos
def extract_text(file_path):
    _, extension = os.path.splitext(file_path)
    
    if extension.lower() == '.pdf':
        text = ""
        with open(file_path, 'rb') as f:
            pdf = PdfReader(f)
            for page in pdf.pages:
                text += page.extract_text() + "\n"
        return text
    
    elif extension.lower() == '.docx':
        doc = docx.Document(file_path)
        return "\n".join([paragraph.text for paragraph in doc.paragraphs])
    
    elif extension.lower() in ['.txt', '.csv', '.md']:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    else:
        raise ValueError(f"Formato de archivo no soportado: {extension}")

# Buscar respuesta (versión simple)
def find_answer(text, question):
    # Dividir el texto en párrafos
    paragraphs = text.split('\n')
    
    # Palabras clave de la pregunta (eliminar palabras comunes)
    keywords = [word.lower() for word in question.split() 
                if word.lower() not in ['el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas', 
                                       'y', 'o', 'a', 'ante', 'bajo', 'con', 'de', 'desde', 
                                       'en', 'entre', 'hacia', 'hasta', 'para', 'por', 'según',
                                       'sin', 'sobre', 'tras', 'qué', 'cuál', 'cómo', 'dónde',
                                       'cuándo', 'quién', 'cuánto']]
    
    # Evaluar cada párrafo
    best_paragraph = ""
    highest_score = 0
    
    for paragraph in paragraphs:
        if len(paragraph.strip()) < 20:  # Ignorar párrafos muy cortos
            continue
            
        # Contar cuántas palabras clave aparecen en el párrafo
        score = sum(1 for keyword in keywords if keyword.lower() in paragraph.lower())
        
        if score > highest_score:
            highest_score = score
            best_paragraph = paragraph
    
    if highest_score > 0:
        return best_paragraph
    else:
        return "No encontré información relacionada con tu pregunta en el documento."

# Página principal con HTML básico
@app.get("/", response_class=HTMLResponse)
async def get_home():
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Chatbot de Documentos</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { 
                padding: 20px; 
                background-color: #f8f9fa;
            }
            .chat-container {
                height: 400px;
                overflow-y: auto;
                border: 1px solid #dee2e6;
                border-radius: 5px;
                padding: 15px;
                background-color: white;
                margin-bottom: 15px;
            }
            .user-message {
                background-color: #e3f2fd;
                padding: 10px 15px;
                border-radius: 15px;
                margin-bottom: 10px;
                max-width: 80%;
                margin-left: auto;
                text-align: right;
            }
            .bot-message {
                background-color: #f1f1f1;
                padding: 10px 15px;
                border-radius: 15px;
                margin-bottom: 10px;
                max-width: 80%;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1 class="text-center mb-4">Chatbot de Documentos</h1>
            
            <div class="row">
                <div class="col-md-8 offset-md-2">
                    <div id="uploadSection">
                        <div class="card mb-4">
                            <div class="card-header">
                                Sube un documento
                            </div>
                            <div class="card-body">
                                <form id="uploadForm">
                                    <div class="mb-3">
                                        <label for="document" class="form-label">Selecciona un archivo (PDF, DOCX, TXT)</label>
                                        <input type="file" class="form-control" id="document" required>
                                    </div>
                                    <button type="submit" class="btn btn-primary">Subir documento</button>
                                </form>
                            </div>
                        </div>
                    </div>
                    
                    <div id="chatSection" style="display: none;">
                        <div class="card mb-4">
                            <div class="card-header d-flex justify-content-between align-items-center">
                                <span>Chat con tu documento</span>
                                <span id="documentName" class="badge bg-info"></span>
                            </div>
                            <div class="card-body">
                                <div id="chatContainer" class="chat-container">
                                    <div class="bot-message">
                                        Hola, puedes hacerme preguntas sobre el documento que has subido.
                                    </div>
                                </div>
                                <form id="questionForm">
                                    <div class="input-group">
                                        <input type="text" id="question" class="form-control" placeholder="Escribe tu pregunta aquí..." required>
                                        <button class="btn btn-primary" type="submit">Enviar</button>
                                    </div>
                                </form>
                            </div>
                        </div>
                        <button id="uploadNew" class="btn btn-outline-secondary">Subir otro documento</button>
                    </div>
                </div>
            </div>
        </div>

        <script>
            let currentDocumentId = null;
            
            document.getElementById('uploadForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                
                const fileInput = document.getElementById('document');
                
                if (fileInput.files.length === 0) {
                    alert('Por favor selecciona un documento');
                    return;
                }
                
                const formData = new FormData();
                formData.append('document', fileInput.files[0]);
                
                try {
                    const response = await fetch('/upload-document/', {
                        method: 'POST',
                        body: formData
                    });
                    
                    const result = await response.json();
                    
                    if (response.ok) {
                        currentDocumentId = result.document_id;
                        document.getElementById('documentName').textContent = fileInput.files[0].name;
                        document.getElementById('uploadSection').style.display = 'none';
                        document.getElementById('chatSection').style.display = 'block';
                    } else {
                        alert('Error: ' + result.detail);
                    }
                } catch (error) {
                    console.error('Error:', error);
                    alert('Ocurrió un error al subir el documento');
                }
            });
            
            document.getElementById('questionForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                
                const questionInput = document.getElementById('question');
                const question = questionInput.value.trim();
                
                if (!question) return;
                
                // Añadir mensaje del usuario al chat
                const chatContainer = document.getElementById('chatContainer');
                const userMessageDiv = document.createElement('div');
                userMessageDiv.className = 'user-message';
                userMessageDiv.textContent = question;
                chatContainer.appendChild(userMessageDiv);
                
                // Scroll al final del chat
                chatContainer.scrollTop = chatContainer.scrollHeight;
                
                // Limpiar el input
                questionInput.value = '';
                
                try {
                    const response = await fetch('/ask-question/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            question: question,
                            document_id: currentDocumentId
                        })
                    });
                    
                    const result = await response.json();
                    
                    // Añadir respuesta del bot al chat
                    const botMessageDiv = document.createElement('div');
                    botMessageDiv.className = 'bot-message';
                    
                    if (response.ok) {
                        botMessageDiv.textContent = result.answer;
                    } else {
                        botMessageDiv.textContent = 'Lo siento, no pude procesar tu pregunta. ' + result.detail;
                    }
                    
                    chatContainer.appendChild(botMessageDiv);
                    
                    // Scroll al final del chat
                    chatContainer.scrollTop = chatContainer.scrollHeight;
                    
                } catch (error) {
                    console.error('Error:', error);
                    
                    // Mensaje de error en el chat
                    const errorMessageDiv = document.createElement('div');
                    errorMessageDiv.className = 'bot-message';
                    errorMessageDiv.textContent = 'Lo siento, ocurrió un error al procesar tu pregunta.';
                    chatContainer.appendChild(errorMessageDiv);
                    
                    // Scroll al final del chat
                    chatContainer.scrollTop = chatContainer.scrollHeight;
                }
            });
            
            document.getElementById('uploadNew').addEventListener('click', () => {
                document.getElementById('uploadSection').style.display = 'block';
                document.getElementById('chatSection').style.display = 'none';
                document.getElementById('document').value = '';
                currentDocumentId = null;
            });
        </script>
    </body>
    </html>
    """

# Ruta para subir documentos
@app.post("/upload-document/")
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
            
            # Almacenar el texto
            documents[document_id] = {
                "filename": document.filename,
                "path": file_path,
                "text": document_text
            }
            
            return {"document_id": document_id, "message": "Documento subido correctamente"}
        
        except Exception as e:
            os.remove(file_path)  # Eliminar archivo si hay error
            raise HTTPException(status_code=400, detail=f"Error al procesar el documento: {str(e)}")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al subir el documento: {str(e)}")

# Ruta para hacer preguntas
@app.post("/ask-question/")
async def ask_question(question_data: Question):
    document_id = question_data.document_id
    question = question_data.question
    
    if document_id not in documents:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    
    try:
        # Obtener el texto del documento
        document_text = documents[document_id]["text"]
        
        # Buscar la respuesta
        answer = find_answer(document_text, question)
        
        return {"answer": answer}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar la pregunta: {str(e)}")

# Punto de entrada para ejecutar la aplicación
if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)