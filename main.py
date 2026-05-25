import sqlite3
from fastapi import FastAPI, WebSocket, UploadFile, File, Form
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import uuid
from datetime import datetime
import numpy as np

# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

DATABASE_PATH = "attendance.db"

def init_database():
    """Initialize SQLite database with required tables."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Create persons table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS persons (
            person_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    
    # Create embeddings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id TEXT NOT NULL,
            embedding BLOB NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (person_id) REFERENCES persons(person_id)
        )
    """)
    
    conn.commit()
    conn.close()

def get_db_connection():
    """Get database connection."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ============================================================================
# FACE PROCESSING (PLACEHOLDER)
# ============================================================================

def extract_embedding(image_data: bytes) -> np.ndarray:
    """
    Extract face embedding from image data.
    PLACEHOLDER: Returns random 512-dim vector.
    In production, use face detection + embedding extraction (e.g., FaceNet, ArcFace).
    """
    return np.random.rand(512).astype(np.float32)

def recognize(image_data: bytes, threshold: float = 0.6) -> dict:
    """
    Recognize face from image.
    PLACEHOLDER: Returns recognition result with random matching.
    In production, use cosine similarity or euclidean distance for matching.
    """
    import random
    
    embedding = extract_embedding(image_data)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM embeddings")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return {
            "recognized": False,
            "person_id": None,
            "name": None,
            "confidence": 0.0
        }
    
    best_match = None
    best_confidence = 0.0
    
    for row in rows:
        confidence = random.random()
        if confidence > best_confidence:
            best_confidence = confidence
            best_match = row
    
    if best_confidence > threshold and best_match:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM persons WHERE person_id = ?", (best_match['person_id'],))
        person = cursor.fetchone()
        conn.close()
        
        return {
            "recognized": True,
            "person_id": best_match['person_id'],
            "name": person['name'] if person else "Unknown",
            "confidence": float(best_confidence)
        }
    
    return {
        "recognized": False,
        "person_id": None,
        "name": None,
        "confidence": 0.0
    }

# ============================================================================
# WEBSOCKET CONNECTION MANAGER
# ============================================================================

class ConnectionManager:
    """Manage WebSocket connections and broadcasting."""
    
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        """Accept and register WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
    
    async def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        
        for conn in disconnected:
            await self.disconnect(conn)

# ============================================================================
# APPLICATION INITIALIZATION
# ============================================================================

manager = ConnectionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown events."""
    init_database()
    print("Database initialized successfully")
    yield
    print("Application shutdown")

app = FastAPI(
    title="Face Recognition Attendance API",
    version="1.0.0",
    description="Production-ready face recognition and attendance system",
    lifespan=lifespan
)

# ============================================================================
# HEALTH CHECK ENDPOINT
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# ============================================================================
# PERSON MANAGEMENT ENDPOINTS
# ============================================================================

@app.post("/api/persons")
async def create_person(name: str):
    """Create a new person."""
    if not name or not name.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "Name is required and cannot be empty"}
        )
    
    person_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO persons (person_id, name, created_at) VALUES (?, ?, ?)",
            (person_id, name.strip(), created_at)
        )
        conn.commit()
        return {
            "person_id": person_id,
            "name": name.strip(),
            "created_at": created_at
        }
    except Exception as e:
        conn.rollback()
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to create person: {str(e)}"}
        )
    finally:
        conn.close()

@app.get("/api/persons")
async def list_persons():
    """List all registered persons."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM persons ORDER BY created_at DESC")
        rows = cursor.fetchall()
        return {
            "persons": [
                {
                    "person_id": row['person_id'],
                    "name": row['name'],
                    "created_at": row['created_at']
                }
                for row in rows
            ],
            "count": len(rows)
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to list persons: {str(e)}"}
        )
    finally:
        conn.close()

# ============================================================================
# FACE ENROLLMENT ENDPOINT
# ============================================================================

@app.post("/api/enrollment/manual")
async def enroll_face(
    person_id: str = Form(...),
    name: str = Form(...),
    file: UploadFile = File(...)
):
    """Enroll a face for a person from uploaded image."""
    if not person_id or not person_id.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "person_id is required"}
        )
    
    if not name or not name.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "name is required"}
        )
    
    try:
        image_data = await file.read()
        if not image_data:
            return JSONResponse(
                status_code=400,
                content={"error": "Uploaded file is empty"}
            )
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"error": f"Failed to read file: {str(e)}"}
        )
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM persons WHERE person_id = ?", (person_id,))
        person = cursor.fetchone()
        
        if not person:
            created_at = datetime.utcnow().isoformat()
            cursor.execute(
                "INSERT INTO persons (person_id, name, created_at) VALUES (?, ?, ?)",
                (person_id, name.strip(), created_at)
            )
            conn.commit()
        
        embedding = extract_embedding(image_data)
        embedding_bytes = embedding.tobytes()
        
        created_at = datetime.utcnow().isoformat()
        cursor.execute(
            "INSERT INTO embeddings (person_id, embedding, created_at) VALUES (?, ?, ?)",
            (person_id, embedding_bytes, created_at)
        )
        conn.commit()
        
        return {
            "success": True,
            "person_id": person_id,
            "name": name.strip(),
            "message": "Face enrolled successfully"
        }
    except Exception as e:
        conn.rollback()
        return JSONResponse(
            status_code=500,
            content={"error": f"Enrollment failed: {str(e)}"}
        )
    finally:
        conn.close()

# ============================================================================
# FACE RECOGNITION ENDPOINT
# ============================================================================

@app.post("/api/recognize")
async def recognize_face(file: UploadFile = File(...)):
    """Recognize a face from uploaded image and broadcast result."""
    try:
        image_data = await file.read()
        if not image_data:
            return JSONResponse(
                status_code=400,
                content={"error": "Uploaded file is empty"}
            )
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"error": f"Failed to read file: {str(e)}"}
        )
    
    try:
        result = recognize(image_data)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Recognition failed: {str(e)}"}
        )
    
    await manager.broadcast({
        "type": "recognition_result",
        "data": result,
        "timestamp": datetime.utcnow().isoformat()
    })
    
    return result

# ============================================================================
# WEBSOCKET ENDPOINT
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time recognition result broadcasting."""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        await manager.disconnect(websocket)

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
