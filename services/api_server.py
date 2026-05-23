# ============================================================
# FASTAPI SERVER - Realtime WebSocket & REST API
# ============================================================
# Implements:
# - REST endpoints for management
# - WebSocket for realtime face recognition updates
# - Attendance recording
# - Unknown candidate management
# - System monitoring

import logging
import asyncio
import cv2
import numpy as np
from datetime import datetime
from typing import Optional, Dict, List
from fastapi import FastAPI, WebSocket, HTTPException, File, UploadFile, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import socketio

logger = logging.getLogger(__name__)


class AttendanceAPIServer:
    """
    FastAPI server for face attendance system.
    
    Features:
    - REST API for CRUD operations
    - WebSocket for realtime updates
    - File upload for manual enrollment
    - System monitoring endpoints
    """
    
    def __init__(self, config: dict, detector=None, recognizer=None, tracker=None, 
                 attendance_service=None, enrollment_service=None, vector_db=None, db_service=None):
        """
        Initialize API server.
        
        Args:
            config: Configuration dict
            detector: FaceDetector instance (optional)
            recognizer: RecognitionEngine instance (optional)
            tracker: ByteTrack instance (optional)
            attendance_service: AttendanceService instance (optional)
            enrollment_service: EnrollmentService instance (optional)
            vector_db: FAISSVectorDB instance (optional)
            db_service: DatabaseService instance (optional)
        """
        self.config = config
        self.detector = detector
        self.recognizer = recognizer
        self.tracker = tracker
        self.attendance_service = attendance_service
        self.enrollment_service = enrollment_service
        self.vector_db = vector_db
        self.db_service = db_service
        
        # FastAPI app
        self.app = FastAPI(title="Face Attendance API", version="1.0.0")
        
        # SocketIO for WebSocket
        self.sio = socketio.AsyncServer(
            async_mode='asgi',
            cors_allowed_origins='*'
        )
        
        # Setup routes
        self._setup_routes()
        self._setup_cors()
    
    def _setup_cors(self):
        """Setup CORS middleware."""
        origins = self.config.get('api', {}).get('cors_origins', ['*'])
        
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    
    def _setup_routes(self):
        """Setup API routes."""
        
        # Health check
        @self.app.get("/health")
        async def health_check():
            return {
                "status": "ok",
                "timestamp": datetime.now().isoformat()
            }
        
        # ========== PERSONS MANAGEMENT ==========
        
        @self.app.post("/api/persons")
        async def create_person(name: str, employee_id: str = None):
            """Create new person."""
            person_id = self.db_service.create_person(
                name=name,
                employee_id=employee_id
            )
            if person_id:
                return {"person_id": person_id, "name": name}
            raise HTTPException(status_code=500, detail="Failed to create person")
        
        @self.app.get("/api/persons")
        async def get_persons():
            """Get all persons."""
            persons = self.db_service.get_all_persons()
            return {
                "count": len(persons),
                "persons": [
                    {"id": p.person_id, "name": p.name, "employee_id": p.employee_id}
                    for p in persons
                ]
            }
        
        @self.app.get("/api/persons/{person_id}")
        async def get_person(person_id: int):
            """Get person details."""
            person = self.db_service.get_person(person_id)
            if person:
                return {
                    "id": person.person_id,
                    "name": person.name,
                    "employee_id": person.employee_id,
                    "created_at": person.created_at.isoformat(),
                }
            raise HTTPException(status_code=404, detail="Person not found")
        
        # ========== ATTENDANCE ENDPOINTS ==========
        
        @self.app.post("/api/attendance/checkin")
        async def checkin(person_id: int, confidence: float = 0.0):
            """Record check-in."""
            success, message = self.attendance_service.record_checkin(
                person_id=person_id,
                confidence=confidence
            )
            return {
                "success": success,
                "message": message,
                "timestamp": datetime.now().isoformat()
            }
        
        @self.app.post("/api/attendance/checkout")
        async def checkout(person_id: int):
            """Record check-out."""
            success, message = self.attendance_service.record_checkout(person_id)
            return {
                "success": success,
                "message": message,
                "timestamp": datetime.now().isoformat()
            }
        
        @self.app.get("/api/attendance/today")
        async def today_attendance():
            """Get today's attendance."""
            attendance = self.attendance_service.get_daily_attendance()
            return {
                "date": datetime.now().date().isoformat(),
                "records": len(attendance),
                "attendance": attendance
            }
        
        @self.app.get("/api/attendance/{person_id}")
        async def person_status(person_id: int):
            """Get person's today status."""
            status = self.attendance_service.get_person_today_status(person_id)
            return {
                "person_id": person_id,
                "date": datetime.now().date().isoformat(),
                "status": status
            }
        
        # ========== ENROLLMENT ENDPOINTS ==========
        
        @self.app.post("/api/enrollment/manual")
        async def manual_enrollment(person_id: int, file: UploadFile = File(...)):
            """Manually enroll person from image."""
            try:
                contents = await file.read()
                nparr = np.frombuffer(contents, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                if frame is None:
                    raise HTTPException(status_code=400, detail="Invalid image")
                
                # Extract embedding
                embedding = self.recognizer.extract_embedding_from_frame(frame)
                if embedding is None:
                    raise HTTPException(status_code=400, detail="No face detected")
                
                # Save embedding
                self.db_service.save_embedding(
                    person_id=person_id,
                    embedding=embedding,
                    quality_score=1.0,
                    source='manual_enrollment'
                )
                
                return {"success": True, "person_id": person_id}
            
            except Exception as e:
                logger.error(f"[API] Manual enrollment error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        # ========== UNKNOWN CANDIDATES ENDPOINTS ==========
        
        @self.app.get("/api/candidates")
        async def get_candidates():
            """Get all unknown candidates."""
            candidates = self.db_service.get_all_unknown_candidates()
            return {
                "total": len(candidates),
                "candidates": [
                    {
                        "id": c.candidate_id,
                        "seen_count": c.seen_count,
                        "avg_quality": c.avg_quality,
                        "first_seen": c.first_seen.isoformat(),
                        "last_seen": c.last_seen.isoformat(),
                    }
                    for c in candidates
                ]
            }
        
        @self.app.post("/api/candidates/{candidate_id}/ignore")
        async def ignore_candidate(candidate_id: int, reason: str = "user_decision"):
            """Ignore unknown candidate."""
            success = self.enrollment_service.ignore_face(candidate_id, reason)
            return {"success": success, "candidate_id": candidate_id}
        
        @self.app.post("/api/candidates/{candidate_id}/convert")
        async def convert_candidate(candidate_id: int, name: str, 
                                   employee_id: str = None):
            """Convert unknown candidate to registered person."""
            try:
                # Create person
                person_id = self.db_service.create_person(name, employee_id)
                if not person_id:
                    raise HTTPException(status_code=500, detail="Failed to create person")
                
                # Get candidate
                candidate = self.db_service.get_unknown_candidate(candidate_id)
                if not candidate:
                    raise HTTPException(status_code=404, detail="Candidate not found")
                
                # Save embeddings
                self.db_service.save_embedding(
                    person_id=person_id,
                    embedding=candidate.best_face_embedding,
                    quality_score=candidate.best_quality_score,
                    source='converted_from_candidate'
                )
                
                # Add to vector database
                self.vector_db.add_embedding(
                    candidate.best_face_embedding,
                    person_id=person_id,
                    quality_score=candidate.best_quality_score
                )
                
                return {
                    "success": True,
                    "person_id": person_id,
                    "name": name
                }
            
            except Exception as e:
                logger.error(f"[API] Conversion error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        # ========== STATISTICS ENDPOINTS ==========
        
        @self.app.get("/api/stats")
        async def get_stats():
            """Get system statistics."""
            return {
                "timestamp": datetime.now().isoformat(),
                "attendance": self.attendance_service.get_stats(),
                "enrollment": self.enrollment_service.get_stats(),
                "recognition": self.recognizer.get_stats(),
                "tracking": self.tracker.get_stats(),
                "vector_db": self.vector_db.get_stats() if self.vector_db else {},
            }
        
        @self.app.get("/api/health/detailed")
        async def detailed_health():
            """Detailed health check."""
            return {
                "status": "ok",
                "timestamp": datetime.now().isoformat(),
                "components": {
                    "detector": "ok",
                    "recognizer": "ok",
                    "tracker": "ok",
                    "database": "ok",
                }
            }
    
    def run(self, host: str = None, port: int = None, workers: int = 1):
        """Run server."""
        if host is None:
            host = self.config.get('api', {}).get('host', '0.0.0.0')
        if port is None:
            port = self.config.get('api', {}).get('port', 8000)
        
        import uvicorn
        uvicorn.run(self.app, host=host, port=port, workers=workers)
