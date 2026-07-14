# ============================================================
# API SERVER (ONLY ROUTES + DEPENDENCY INJECTION)
# ============================================================

import os
import logging
import uuid
import base64
import time
import threading
import cv2
import numpy as np
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, File, UploadFile, Form, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from services.websocket_manager import WebSocketManager

logger = logging.getLogger(__name__)


# ============================================================
# REQUEST/RESPONSE MODELS
# ============================================================

class ScanRequest(BaseModel):
    """Backend camera sends scan event."""
    member_id: Optional[int] = None  # None if unknown
    image_base64: Optional[str] = None
    confidence: Optional[float] = None
    face_quality: Optional[str] = None
    phase: Optional[str] = "confirmed"  # "pending" or "confirmed"


class AckRequest(BaseModel):
    """Acknowledge scan request."""
    scan_id: str


# ============================================================
# DB CONNECTION (deprecated - use db_service instead)
# ============================================================

def get_db():
    import sqlite3, os
    appdata = os.environ.get('APPDATA', os.path.expanduser('~'))
    db_dir = os.path.join(appdata, 'face_attendance')
    os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(os.path.join(db_dir, "face_attendance.db"))
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================
# API SERVER CLASS
# ============================================================

class AttendanceAPIServer:
    def __init__(
        self,
        config,
        detector=None,
        embedders=None,
        recognizer=None,
        tracker=None,
        attendance_service=None,
        enrollment_service=None,
        vector_db=None,
        db_service=None,
        quality_filter=None,
        mode_change_callback=None,
    ):
        self.config = config
        self.embedders = embedders
        self.detector = detector
        self.recognizer = recognizer
        self.tracker = tracker
        self.attendance_service = attendance_service
        self.enrollment_service = enrollment_service
        self.vector_db = vector_db
        self.db_service = db_service
        self.quality_filter = quality_filter
        self.mode_change_callback = mode_change_callback

        self.camera_paused = threading.Event()
        self.ws_manager = WebSocketManager()
        self.current_mode = config.get("mode", "accuracy") if hasattr(config, 'get') else "accuracy"
        self.mode_config = config
        self.app = FastAPI(title="Face Attendance API", version="1.0.0")

        self.app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=r"https://.*\.vercel\.app",
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        import os
        self.scan_images_dir = "scan_images"
        os.makedirs(self.scan_images_dir, exist_ok=True)

        self._setup_routes()
        self._start_cleanup_task()

    # ========================================================
    # ROUTES
    # ========================================================
    def _setup_routes(self):

        db = self.db_service
        recognizer = self.recognizer
        vector_db = self.vector_db
        embedders = self.embedders

        from fastapi.staticfiles import StaticFiles
        self.app.mount("/images", StaticFiles(directory=self.scan_images_dir), name="images")

        # ================= HEALTH =================
        @self.app.get("/health")
        async def health():
            """Check server health and stats."""
            try:
                if not db:
                    return {"status": "error", "message": "DB not available"}
                
                persons = db.get_all_persons()
                pending_scans = db.get_pending_scans()
                registered_faces = db.get_all_registered_faces()
                
                return {
                    "status": "ok",
                    "time": datetime.now().isoformat(),
                    "registered_persons": len(persons),
                    "pending_scans": len(pending_scans),
                    "registered_faces": len(registered_faces),
                }
            except Exception as e:
                logger.error(f"Health check error: {e}")
                return {"status": "error", "message": str(e)}

        # ================= PERSON =================
        @self.app.post("/api/persons")
        async def create_person(name: str):
            """Create a new person for registration."""
            if not db:
                raise HTTPException(500, "DB not available")

            person_id = db.create_person(name=name)
            if not person_id:
                raise HTTPException(500, "Failed to create person")
            
            return {
                "success": True,
                "person_id": person_id,
                "name": name
            }

        @self.app.get("/api/persons")
        async def get_persons():
            """Get all registered persons."""
            if not db:
                raise HTTPException(500, "DB not available")
            
            persons = db.get_all_persons()
            return {
                "success": True,
                "count": len(persons),
                "persons": [
                    {
                        "person_id": p.person_id,
                        "name": p.name,
                        "employee_id": p.employee_id,
                        "is_active": p.is_active,
                        "created_at": p.created_at.isoformat() if hasattr(p, 'created_at') else None
                    }
                    for p in persons
                ]
            }

        # ================= ENROLLMENT =================
        @self.app.post("/api/enrollment/manual")
        async def enroll(
            person_id: str = Form(...),
            name: str = Form(...),
            file: UploadFile = File(...)
        ):
            """
            Enroll a person with face image.
            If person_id already exists, reuse it (no duplicate creation).
            """
            if not db or not recognizer or not embedders:
                raise HTTPException(500, "Services not ready")

            try:
                person_id_int = int(person_id)

                # ----- CHECK IF PERSON EXISTS -----
                existing_person = db.get_person(person_id_int)

                if existing_person:
                    # Person exists – use the existing person_id
                    final_person_id = person_id_int
                    logger.info(f"Person ID {person_id_int} already exists. Adding new face embedding.")
                else:
                    # Person does NOT exist – create new
                    final_person_id = db.create_person(
                        person_id=person_id_int,
                        name=name
                    )
                    if not final_person_id:
                        raise HTTPException(500, "Failed to create person")
                    logger.info(f"Created new person ID {final_person_id}")

                # Read image
                image_bytes = await file.read()
                nparr = np.frombuffer(image_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

                if frame is None:
                    raise HTTPException(400, "Invalid image file")

                # Extract embedding
                embedding = embedders.extract_embedding(frame)
                if embedding is None:
                    raise HTTPException(400, "No face detected in image")

                # Save embedding (adds new embedding for the person)
                recognizer.add_embedding(
                    person_id=str(final_person_id),
                    embedding=embedding,
                    quality_score=1.0,
                    source="manual_enrollment"
                )

                return {
                    "success": True,
                    "person_id": final_person_id,
                    "name": name,
                    "message": "Face enrolled successfully" + (" (existing person reused)" if existing_person else "")
                }

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Enrollment error: {e}")
                raise HTTPException(500, f"Enrollment failed: {str(e)}")

        # ================= RECOGNITION =================
        @self.app.post("/api/recognize")
        async def recognize(file: UploadFile = File(...)):
            """
            Recognize a face from an image.
            Compares embedding with stored embeddings.
            Returns matched person or unknown.
            """
            if not recognizer or not embedders:
                raise HTTPException(500, "Recognizer not available")

            try:
                # Read image
                image_bytes = await file.read()
                nparr = np.frombuffer(image_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                if frame is None:
                    raise HTTPException(400, "Invalid image file")

                # Extract embedding
                embedding = embedders.extract_embedding(frame)
                if embedding is None:
                    return {
                        "success": False,
                        "recognized": False,
                        "person_id": None,
                        "name": None,
                        "confidence": 0.0,
                        "message": "No face detected in image"
                    }

                # Recognize face
                result, best_score, all_scores = recognizer.identify(
                    embedding=embedding,
                    threshold=0.6  # Minimum confidence threshold
                )

                return {
                    "success": True,
                    "recognized": result.get("recognized", False),
                    "person_id": result.get("person_id"),
                    "name": result.get("name"),
                    "confidence": result.get("confidence", 0.0),
                    "best_score": float(best_score),
                    "all_scores": all_scores
                }
            
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Recognition error: {e}")
                raise HTTPException(500, f"Recognition failed: {str(e)}")

        # ================= SCAN (Backend-Driven) =================
        @self.app.post("/scan")
        async def receive_scan(request: ScanRequest):
            """
            Backend camera sends scan event.
            Includes member_id (if recognized) and optional image.
            Flutter polls and gets these events.
            """
            if not db:
                raise HTTPException(500, "DB not available")

            try:
                scan_id = str(uuid.uuid4())
                timestamp = time.time()
                image_url = None
                
                # Save image to disk if present
                if request.image_base64:
                    try:
                        import base64 as b64
                        img_data = request.image_base64
                        if "," in img_data:
                            img_data = img_data.split(",")[1]
                        img_bytes = b64.b64decode(img_data)
                        filename = f"scan_{scan_id}.jpg"
                        filepath = os.path.join(self.scan_images_dir, filename)
                        with open(filepath, "wb") as f:
                            f.write(img_bytes)
                        image_url = f"/images/{filename}"
                    except Exception as e:
                        logger.warning(f"Failed to save scan image: {e}")
                
                success = db.add_scan(
                    scan_id=scan_id,
                    member_id=request.member_id,
                    timestamp=timestamp,
                    image_base64=request.image_base64,
                    image_url=image_url,
                    confidence=request.confidence,
                    face_quality=request.face_quality,
                )
                
                if not success:
                    raise HTTPException(500, "Failed to store scan")

                # Broadcast scan event to all connected WebSocket clients
                scan_event = {
                    "id": scan_id,
                    "member_id": request.member_id,
                    "timestamp": timestamp,
                    "image_base64": request.image_base64,
                    "image_url": image_url,
                    "confidence": request.confidence,
                    "face_quality": request.face_quality,
                    "phase": request.phase or "confirmed",
                }
                await self.ws_manager.broadcast_scan(scan_event)
                
                logger.info(f"🔥 Scan received: {scan_id} | member={request.member_id}")
                
                return {
                    "success": True,
                    "scan_id": scan_id,
                    "timestamp": timestamp,
                    "image_url": image_url,
                }
            
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Scan error: {e}")
                raise HTTPException(500, f"Scan failed: {str(e)}")

        # ================= REGISTER FACE (Backend-Driven) =================
        @self.app.post("/register")
        async def register_face(
            member_id: int = Form(...),
            image_base64: Optional[str] = Form(None),
            file: Optional[UploadFile] = File(None)
        ):
            """
            Register a face for a member (backend enrollment).
            Can accept image as base64 or file upload.
            """
            if not db:
                raise HTTPException(500, "DB not available")

            try:
                import os
                
                # Get or create faces directory
                faces_dir = "registered_faces"
                os.makedirs(faces_dir, exist_ok=True)
                
                # Handle image input
                if file:
                    # Read from file upload
                    image_bytes = await file.read()
                    image_data = base64.b64encode(image_bytes).decode()
                elif image_base64:
                    # Use provided base64
                    if "," in image_base64:
                        image_data = image_base64.split(",")[1]
                    else:
                        image_data = image_base64
                else:
                    raise HTTPException(400, "image_base64 or file required")
                
                # Decode and save
                image_bytes = base64.b64decode(image_data)
                image_path = os.path.join(faces_dir, f"{member_id}.jpg")
                
                with open(image_path, "wb") as f:
                    f.write(image_bytes)
                
                # Store in database
                success = db.register_face(
                    member_id=member_id,
                    image_path=image_path,
                    image_base64=image_data
                )
                
                if not success:
                    raise HTTPException(500, "Failed to register face")
                
                logger.info(f"📸 Face registered for member {member_id}")
                
                return {
                    "success": True,
                    "member_id": member_id,
                    "image_path": image_path
                }
            
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Registration error: {e}")
                raise HTTPException(500, f"Registration failed: {str(e)}")

        # ================= POLLING (Flutter polls for scans) =================
        @self.app.get("/poll")
        async def poll_scans(last_timestamp: float = None, last_id: str = None):
            """
            Flutter polls this endpoint to get pending scans from backend camera.
            Returns list of new scan events since last_timestamp.
            """
            if not db:
                raise HTTPException(500, "DB not available")

            try:
                # Resolve timestamp from last_id if provided
                if last_id and last_timestamp is None:
                    # Find the timestamp of the given scan_id
                    pending = db.get_pending_scans()
                    for scan in pending:
                        if scan['id'] == last_id:
                            last_timestamp = scan['timestamp']
                            break
                
                # Get pending scans
                scans = db.get_pending_scans(last_timestamp=last_timestamp)
                
                return {
                    "success": True,
                    "count": len(scans),
                    "scans": scans
                }
            
            except Exception as e:
                logger.error(f"Poll error: {e}")
                raise HTTPException(500, f"Poll failed: {str(e)}")

        # ================= ACKNOWLEDGE SCAN (Flutter acks after processing) =================
        @self.app.post("/ack")
        async def ack_scan(request: AckRequest):
            if not db:
                raise HTTPException(500, "DB not available")

            try:
                # First, retrieve the scan to get image path
                # We need a method in db_service to get scan by id
                scan = db.get_scan_by_id(request.scan_id)  # implement this
                if scan and scan.get('image_path'):
                    try:
                        os.remove(scan['image_path'])
                        logger.info(f"[API] Deleted image {scan['image_path']}")
                    except Exception as e:
                        logger.warning(f"[API] Could not delete image: {e}")
                
                success = db.ack_scan(request.scan_id)
                if not success:
                    raise HTTPException(500, "Failed to acknowledge scan")
                
                logger.info(f"✅ ACK for {request.scan_id}")
                return {"success": True, "scan_id": request.scan_id}
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Ack error: {e}")
                raise HTTPException(500, f"Ack failed: {str(e)}")

        # ================= DEBUG ENDPOINTS =================
        @self.app.get("/debug/pending")
        async def debug_pending():
            """Debug: Show all pending scans."""
            if not db:
                raise HTTPException(500, "DB not available")
            
            scans = db.get_pending_scans()
            return {
                "count": len(scans),
                "scans": scans
            }

        @self.app.get("/debug/faces")
        async def debug_faces():
            """Debug: Show all registered faces."""
            if not db:
                raise HTTPException(500, "DB not available")
            
            faces = db.get_all_registered_faces()
            return {
                "count": len(faces),
                "faces": faces
            }

        @self.app.get("/test_unknown")
        async def test_unknown():
            """Debug: Add test unknown scan."""
            if not db:
                raise HTTPException(500, "DB not available")
            
            dummy_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            scan_id = str(uuid.uuid4())
            
            success = db.add_scan(
                scan_id=scan_id,
                member_id=None,
                timestamp=time.time(),
                image_base64=dummy_b64
            )
            
            return {
                "status": "test unknown scan added",
                "scan_id": scan_id,
                "success": success
            }

        # ================= WEBSOCKET (Real-time scan push) =================
        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await self.ws_manager.connect(websocket)
            try:
                # Send current mode on connect
                await websocket.send_json({
                    "type": "hello",
                    "mode": self.current_mode,
                    "timestamp": time.time(),
                })
                # Keep connection alive — listen for client pings
                while True:
                    data = await websocket.receive_text()
                    try:
                        msg = json.loads(data)
                        if msg.get("type") == "ping":
                            await websocket.send_json({"type": "pong"})
                    except json.JSONDecodeError:
                        pass
            except WebSocketDisconnect:
                pass
            except Exception as e:
                logger.warning(f"[WS] Error: {e}")
            finally:
                await self.ws_manager.disconnect(websocket)

        # ================= MODE SWITCHING (Runtime toggle) =================
        @self.app.get("/api/mode")
        async def get_mode():
            """Get current recognition mode and effective params."""
            params = self._resolve_mode_params()
            return {
                "mode": self.current_mode,
                "available": ["speed", "accuracy"],
                "params": {
                    "recognition.similarity_threshold": params.get("recognition.similarity_threshold", 0.6),
                    "recognition.min_stable_frames": int(params.get("recognition.min_stable_frames", 3)),
                    "recognition.recognition_threshold": params.get("recognition.recognition_threshold", 0.5),
                    "quality_filter.blur_threshold": params.get("quality_filter.blur_threshold", 40.0),
                    "quality_filter.min_face_size": int(params.get("quality_filter.min_face_size", 30)),
                },
            }

        @self.app.post("/api/mode")
        async def set_mode(mode: str = Form(...)):
            """Switch recognition mode at runtime: 'speed' or 'accuracy'."""
            try:
                changed = self.apply_mode(mode)
                # Broadcast mode change to all WebSocket clients
                await self.ws_manager.broadcast_mode_change(mode)
                return {
                    "success": True,
                    "mode": mode,
                    "changed": list(changed.keys()),
                }
            except ValueError as e:
                raise HTTPException(400, str(e))

        @self.app.post("/camera/pause")
        async def pause_camera():
            """Tell Python to release the camera and pause recognition."""
            self.camera_paused.set()
            return {"success": True, "message": "Camera paused for Flutter"}
        @self.app.post("/camera/resume")
        async def resume_camera():
            """Tell Python to reacquire the camera and resume recognition."""
            self.camera_paused.clear()
            return {"success": True, "message": "Camera resumed"}

        @self.app.get("/camera/status")
        async def camera_status():
            """Get current camera pause status."""
            return {"paused": self.camera_paused.is_set()}

    # ========================================================
    # MODE MANAGEMENT
    # ========================================================
    def _resolve_mode_params(self, mode: str = None):
        """Resolve effective params for given mode. Returns (section_key, params_dict)."""
        mode = mode or self.current_mode
        mode_profiles = {}
        if hasattr(self.config, 'get_section'):
            mode_profiles = self.config.get_section("modes")
        elif isinstance(self.config, dict):
            mode_profiles = self.config.get("modes", {})

        profile = mode_profiles.get(mode, {})
        flat = {}
        for section, values in profile.items():
            for key, val in values.items():
                flat[f"{section}.{key}"] = val
        return flat

    def apply_mode(self, mode: str):
        """Apply mode profile at runtime. Returns dict of changed params."""
        if mode not in ("speed", "accuracy"):
            raise ValueError(f"Invalid mode: {mode}. Use 'speed' or 'accuracy'.")

        old_mode = self.current_mode
        self.current_mode = mode
        params = self._resolve_mode_params(mode)

        changed = {}
        if self.recognizer:
            new_sim = params.get("recognition.similarity_threshold")
            if new_sim is not None:
                changed["recognition.similarity_threshold"] = self.recognizer.similarity_threshold
                self.recognizer.similarity_threshold = new_sim

            new_min_frames = params.get("recognition.min_stable_frames")
            if new_min_frames is not None:
                changed["recognition.min_stable_frames"] = self.recognizer.min_stable_frames
                self.recognizer.min_stable_frames = int(new_min_frames)

            new_rec_thresh = params.get("recognition.recognition_threshold")
            if new_rec_thresh is not None:
                changed["recognition.recognition_threshold"] = self.recognizer.recognition_threshold
                self.recognizer.recognition_threshold = new_rec_thresh

        if self.quality_filter:
            qf_params = {}
            for k in ("blur_threshold", "min_face_size", "max_yaw", "max_pitch", "max_roll"):
                kval = f"quality_filter.{k}"
                if kval in params:
                    qf_params[k] = params[kval]
            if qf_params:
                changed["quality_filter"] = qf_params
                self.quality_filter.apply_mode(qf_params)

        # Notify mode change callback (live_ip_cam uses this)
        if self.mode_change_callback:
            try:
                self.mode_change_callback(mode, params)
            except Exception as e:
                logger.error(f"[MODE] Callback error: {e}")

        logger.info(f"[MODE] Switched: {old_mode} → {mode}. Changed: {list(changed.keys())}")
        return changed

    # ========================================================
    # BACKGROUND CLEANUP TASK
    # ========================================================
    def _start_cleanup_task(self):
        """Start background task to clean up old scans."""
        def cleanup_loop():
            while True:
                time.sleep(3600)  # Run every hour
                try:
                    if self.db_service:
                        deleted = self.db_service.cleanup_old_scans(max_age_seconds=3600)
                        if deleted > 0:
                            logger.info(f"🧹 Cleaned up {deleted} old scans")
                except Exception as e:
                    logger.error(f"Cleanup error: {e}")
        
        thread = threading.Thread(target=cleanup_loop, daemon=True)
        thread.start()
     
    
    
    
    # ========================================================
    # RUN SERVER
    # ========================================================
    def run(self, host="0.0.0.0", port=8000):
        import uvicorn
        uvicorn.run(self.app, host=host, port=port)