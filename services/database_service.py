# ============================================================
# DATABASE SERVICE - Core Data Persistence Layer
# ============================================================
# SQLAlchemy-based service for all database operations:
# - Persons and embeddings
# - Attendance records
# - Unknown candidates
# - Ignored faces

import logging
import threading
from typing import Optional, List, Dict
from datetime import datetime, timedelta
import numpy as np

logger = logging.getLogger(__name__)


class DatabaseService:
    """
    SQLAlchemy-based database service for face attendance system.
    
    Manages:
    - Person registration and profiles
    - Face embeddings storage
    - Attendance records
    - Unknown candidate enrollment
    - Ignored face tracking
    """
    
    def __init__(self, session_maker, use_sqlite: bool = True):
        """
        Initialize database service.
        
        Args:
            session_maker: SQLAlchemy SessionLocal factory
            use_sqlite: Use SQLite (False = PostgreSQL)
        """
        self.SessionLocal = session_maker
        self.use_sqlite = use_sqlite
        self.lock = threading.Lock()
    
    # ========== PERSON MANAGEMENT ==========
    
    def create_person(
        self,
        person_id: int,
        name: str,
        metadata: dict = None
    ) -> Optional[int]:
        try:
            from models.database import Person

            session = self.SessionLocal()

            person = Person(
                person_id=person_id,
                name=name,
                is_active=True,
                meta_data=self._dict_to_json(metadata or {})
            )

            session.add(person)
            session.commit()

            created_person_id = person.person_id

            session.close()

            logger.info(f"[DB] Created person: {name} (ID={created_person_id})")

            return created_person_id

        except Exception as e:
            logger.error(f"[DB] Failed to create person: {e}")
            return None
    
    def get_person(self, person_id: int):
        """Get person by ID."""
        try:
            from models.database import Person
            
            session = self.SessionLocal()
            person = session.query(Person).filter(Person.person_id == person_id).first()
            session.close()
            return person
        except Exception as e:
            logger.error(f"[DB] Failed to get person: {e}")
            return None
    
    def get_person_name(self, person_id: int) -> str:
        """Get person name."""
        person = self.get_person(person_id)
        return person.name if person else f"Unknown_{person_id}"
    
    def get_all_persons(self) -> List:
        """Get all registered persons."""
        try:
            from models.database import Person
            
            session = self.SessionLocal()
            persons = session.query(Person).filter(Person.is_active == True).all()
            session.close()
            return persons
        except Exception as e:
            logger.error(f"[DB] Failed to get persons: {e}")
            return []
    
    # ========== EMBEDDINGS MANAGEMENT ==========
    def get_all_embeddings(self):
        """Get all embeddings from database."""
        try:
            from models.database import FaceEmbedding, bytes_to_embedding
            
            session = self.SessionLocal()
            records = session.query(FaceEmbedding).all()
            
            rows = []
            for record in records:
                embedding = bytes_to_embedding(record.embedding)
                rows.append((record.person_id, embedding))
            
            session.close()
            return rows
        except Exception as e:
            logger.error(f"[DB] Failed to get all embeddings: {e}")
            return []
    
    def save_embedding(self, person_id: int, embedding: np.ndarray,
                      quality_score: float, source: str = 'manual',
                      face_hash: str = None) -> Optional[int]:
        """Save face embedding for person."""
        try:
            from models.database import FaceEmbedding, embedding_to_bytes
            
            session = self.SessionLocal()
            emb_record = FaceEmbedding(
                person_id=person_id,
                embedding=embedding_to_bytes(embedding),
                quality_score=quality_score,
                source=source,
                face_hash=face_hash,
            )
            session.add(emb_record)
            session.commit()
            emb_id = emb_record.embedding_id
            session.close()
            
            logger.debug(f"[DB] Saved embedding {emb_id} for person {person_id}")
            return emb_id
        except Exception as e:
            logger.error(f"[DB] Failed to save embedding: {e}")
            return None
    
    def get_embeddings_for_person(self, person_id: int) -> List[np.ndarray]:
        """Get all embeddings for person."""
        try:
            from models.database import FaceEmbedding, bytes_to_embedding
            
            session = self.SessionLocal()
            records = session.query(FaceEmbedding).filter(
                FaceEmbedding.person_id == person_id
            ).all()
            
            embeddings = []
            for record in records:
                emb = bytes_to_embedding(record.embedding)
                embeddings.append(emb)
            
            session.close()
            return embeddings
        except Exception as e:
            logger.error(f"[DB] Failed to get embeddings: {e}")
            return []
    
    def get_average_embedding(self, person_id: int) -> Optional[np.ndarray]:
        """Get averaged embedding for person."""
        embeddings = self.get_embeddings_for_person(person_id)
        if not embeddings:
            return None
        
        avg_emb = np.mean(embeddings, axis=0)
        norm = np.linalg.norm(avg_emb)
        if norm > 0:
            avg_emb = avg_emb / norm
        return avg_emb
    
    # ========== ATTENDANCE MANAGEMENT ==========
    
    def create_attendance_record(self, person_id: int, check_in_time: datetime,
                                check_out_time: datetime = None,
                                confidence_avg: float = 0.0,
                                track_duration: int = 0,
                                device: str = 'webcam',
                                notes: str = None) -> Optional[int]:
        """Create attendance record."""
        try:
            from models.database import AttendanceRecord
            
            session = self.SessionLocal()
            record = AttendanceRecord(
                person_id=person_id,
                check_in_time=check_in_time,
                check_out_time=check_out_time,
                confidence_avg=confidence_avg,
                track_duration=track_duration,
                device=device,
                notes=notes,
            )
            session.add(record)
            session.commit()
            record_id = record.record_id
            session.close()
            
            return record_id
        except Exception as e:
            logger.error(f"[DB] Failed to create attendance record: {e}")
            return None
    
    def get_latest_checkin(self, person_id: int) -> Optional[datetime]:
        """Get last check-in time for person."""
        try:
            from models.database import AttendanceRecord
            
            session = self.SessionLocal()
            record = session.query(AttendanceRecord).filter(
                AttendanceRecord.person_id == person_id
            ).order_by(AttendanceRecord.check_in_time.desc()).first()
            
            check_in = record.check_in_time if record else None
            session.close()
            return check_in
        except Exception as e:
            logger.error(f"[DB] Failed to get latest checkin: {e}")
            return None
    
    def get_latest_unchecked_record(self, person_id: int):
        """Get latest unchecked-out record."""
        try:
            from models.database import AttendanceRecord
            
            session = self.SessionLocal()
            record = session.query(AttendanceRecord).filter(
                AttendanceRecord.person_id == person_id,
                AttendanceRecord.check_out_time == None
            ).order_by(AttendanceRecord.check_in_time.desc()).first()
            
            session.close()
            return record
        except Exception as e:
            logger.error(f"[DB] Failed to get unchecked record: {e}")
            return None
    
    def update_checkout(self, record_id: int, check_out_time: datetime,
                       duration_seconds: int) -> bool:
        """Update check-out time."""
        try:
            from models.database import AttendanceRecord
            
            session = self.SessionLocal()
            record = session.query(AttendanceRecord).filter(
                AttendanceRecord.record_id == record_id
            ).first()
            
            if record:
                record.check_out_time = check_out_time
                record.duration_seconds = duration_seconds
                session.commit()
                session.close()
                return True
            
            session.close()
            return False
        except Exception as e:
            logger.error(f"[DB] Failed to update checkout: {e}")
            return False
    
    def get_attendance_by_date(self, date: datetime) -> List:
        """Get all attendance records for a date."""
        try:
            from models.database import AttendanceRecord
            
            session = self.SessionLocal()
            start_date = datetime.combine(date.date(), datetime.min.time())
            end_date = datetime.combine(date.date(), datetime.max.time())
            
            records = session.query(AttendanceRecord).filter(
                AttendanceRecord.check_in_time >= start_date,
                AttendanceRecord.check_in_time <= end_date
            ).all()
            
            session.close()
            return records
        except Exception as e:
            logger.error(f"[DB] Failed to get attendance by date: {e}")
            return []
    
    def get_attendance_range(self, start_date: datetime, 
                            end_date: datetime) -> List:
        """Get attendance records for date range."""
        try:
            from models.database import AttendanceRecord
            
            session = self.SessionLocal()
            records = session.query(AttendanceRecord).filter(
                AttendanceRecord.check_in_time >= start_date,
                AttendanceRecord.check_in_time <= end_date
            ).all()
            
            session.close()
            return records
        except Exception as e:
            logger.error(f"[DB] Failed to get attendance range: {e}")
            return []
    
    # ========== UNKNOWN CANDIDATES MANAGEMENT ==========
    
    def create_unknown_candidate(self, embedding: np.ndarray,
                                face_image_path: str,
                                quality_score: float,
                                embedding_hash: str,
                                embedding_cluster_id: str) -> Optional[int]:
        """Create unknown candidate."""
        try:
            from models.database import UnknownCandidate, embedding_to_bytes
            
            session = self.SessionLocal()
            candidate = UnknownCandidate(
                embedding_cluster_id=embedding_cluster_id,
                best_face_embedding=embedding_to_bytes(embedding),
                best_face_image_path=face_image_path,
                best_quality_score=quality_score,
                seen_count=1,
                first_seen=datetime.now(),
                last_seen=datetime.now(),
                avg_quality=quality_score,
                collected_embeddings_count=1,
            )
            session.add(candidate)
            session.commit()
            candidate_id = candidate.candidate_id
            session.close()
            
            return candidate_id
        except Exception as e:
            logger.error(f"[DB] Failed to create unknown candidate: {e}")
            return None
    
    def get_unknown_candidate(self, candidate_id: int):
        """Get unknown candidate."""
        try:
            from models.database import UnknownCandidate, bytes_to_embedding
            
            session = self.SessionLocal()
            record = session.query(UnknownCandidate).filter(
                UnknownCandidate.candidate_id == candidate_id
            ).first()
            
            if record and record.best_face_embedding:
                # Convert bytes to numpy array
                record.best_face_embedding = bytes_to_embedding(record.best_face_embedding)
                if record.avg_embedding:
                    record.avg_embedding = bytes_to_embedding(record.avg_embedding)
            
            session.close()
            return record
        except Exception as e:
            logger.error(f"[DB] Failed to get unknown candidate: {e}")
            return None
    
    def get_all_unknown_candidates(self) -> List:
        """Get all unknown candidates."""
        try:
            from models.database import UnknownCandidate, bytes_to_embedding
            
            session = self.SessionLocal()
            records = session.query(UnknownCandidate).filter(
                UnknownCandidate.is_merged == False
            ).all()
            
            for record in records:
                if record.best_face_embedding:
                    record.best_face_embedding = bytes_to_embedding(record.best_face_embedding)
                if record.avg_embedding:
                    record.avg_embedding = bytes_to_embedding(record.avg_embedding)
            
            session.close()
            return records
        except Exception as e:
            logger.error(f"[DB] Failed to get unknown candidates: {e}")
            return []
    
    def update_unknown_candidate(self, candidate_id: int, **kwargs) -> bool:
        """Update unknown candidate fields."""
        try:
            from models.database import UnknownCandidate, embedding_to_bytes
            
            session = self.SessionLocal()
            record = session.query(UnknownCandidate).filter(
                UnknownCandidate.candidate_id == candidate_id
            ).first()
            
            if record:
                for key, value in kwargs.items():
                    if key in ['best_face_embedding', 'avg_embedding'] and isinstance(value, np.ndarray):
                        value = embedding_to_bytes(value)
                    setattr(record, key, value)
                
                record.last_seen = datetime.now()
                session.commit()
                session.close()
                return True
            
            session.close()
            return False
        except Exception as e:
            logger.error(f"[DB] Failed to update unknown candidate: {e}")
            return False
    
    def mark_candidate_merged(self, source_id: int, target_id: int) -> bool:
        """Mark candidate as merged into another."""
        return self.update_unknown_candidate(
            source_id,
            is_merged=True,
            merged_into_candidate_id=target_id
        )
    
    # ========== IGNORED FACES MANAGEMENT ==========
    
    def create_ignored_face(self, embedding_cluster_id: str, reason: str,
                          expires_at: datetime, embedding: np.ndarray) -> bool:
        """Create ignored face entry."""
        try:
            from models.database import IgnoredFace, embedding_to_bytes
            
            session = self.SessionLocal()
            ignored = IgnoredFace(
                embedding_cluster_id=embedding_cluster_id,
                reason=reason,
                created_at=datetime.now(),
                expires_at=expires_at,
                representative_embedding=embedding_to_bytes(embedding),
            )
            session.add(ignored)
            session.commit()
            session.close()
            return True
        except Exception as e:
            logger.error(f"[DB] Failed to create ignored face: {e}")
            return False
    
    def is_face_ignored(self, candidate_id: int) -> bool:
        """Check if face is ignored."""
        try:
            candidate = self.get_unknown_candidate(candidate_id)
            if candidate and candidate.ignored_until:
                return candidate.ignored_until > datetime.now()
            return False
        except Exception as e:
            logger.error(f"[DB] Failed to check ignored face: {e}")
            return False
    
    def remove_ignored_face(self, embedding_cluster_id: str) -> bool:
        """Remove ignore status."""
        try:
            from models.database import IgnoredFace
            
            session = self.SessionLocal()
            session.query(IgnoredFace).filter(
                IgnoredFace.embedding_cluster_id == embedding_cluster_id
            ).delete()
            session.commit()
            session.close()
            return True
        except Exception as e:
            logger.error(f"[DB] Failed to remove ignored face: {e}")
            return False
    
    # ========== PENDING SCANS (Backend-Driven Polling) ==========
    
    def add_scan(self, scan_id: str, member_id: Optional[int], timestamp: float,
                 image_base64: str = None, recognized: bool = False,
                 confidence: float = None, face_quality: str = None,
                 image_url: str = None) -> bool:
        """Add a pending scan from backend camera."""
        try:
            from models.database import PendingScan
            
            session = self.SessionLocal()
            scan = PendingScan(
                id=scan_id,
                member_id=member_id,
                timestamp=timestamp,
                image_base64=image_base64,
                image_url=image_url,
                recognized=recognized,
                confidence=confidence,
                face_quality=face_quality,
            )
            session.add(scan)
            session.commit()
            session.close()
            
            logger.info(f"[DB] Added scan: {scan_id} (member={member_id})")
            return True
        except Exception as e:
            logger.error(f"[DB] Failed to add scan: {e}")
            return False
    
    def get_pending_scans(self, last_timestamp: float = None) -> List[Dict]:
        """Get pending scans since last_timestamp."""
        try:
            from models.database import PendingScan
            
            session = self.SessionLocal()
            
            if last_timestamp is None:
                records = session.query(PendingScan).order_by(PendingScan.timestamp.asc()).all()
            else:
                records = session.query(PendingScan).filter(
                    PendingScan.timestamp > last_timestamp
                ).order_by(PendingScan.timestamp.asc()).all()
            
            scans = []
            for r in records:
                scans.append({
                    'id': r.id,
                    'member_id': r.member_id,
                    'timestamp': r.timestamp,
                    'image_base64': r.image_base64,
                    'image_url': r.image_url,
                    'recognized': r.recognized,
                    'confidence': r.confidence,
                    'face_quality': r.face_quality,
                })
            
            session.close()
            return scans
        except Exception as e:
            logger.error(f"[DB] Failed to get pending scans: {e}")
            return []

    def get_scan_by_id(self, scan_id: str) -> Optional[Dict]:
        try:
            from models.database import PendingScan
            session = self.SessionLocal()
            record = session.query(PendingScan).filter(PendingScan.id == scan_id).first()
            if record:
                result = {
                    'id': record.id,
                    'member_id': record.member_id,
                    'image_base64': record.image_base64,
                    'timestamp': record.timestamp,
                }
                session.close()
                return result

            session.close()
            return None
        except Exception as e:
            logger.error(f"[DB] Failed to get scan: {e}")
            return None

    def ack_scan(self, scan_id: str) -> bool:
        """Acknowledge and delete a scan."""
        try:
            from models.database import PendingScan
            
            session = self.SessionLocal()
            session.query(PendingScan).filter(PendingScan.id == scan_id).delete()
            session.commit()
            session.close()
            
            logger.info(f"[DB] Acknowledged scan: {scan_id}")
            return True
        except Exception as e:
            logger.error(f"[DB] Failed to ack scan: {e}")
            return False
    
    def cleanup_old_scans(self, max_age_seconds: int = 3600) -> int:
        """Delete old scans (default 1 hour)."""
        try:
            from models.database import PendingScan
            from datetime import datetime, timedelta
            
            session = self.SessionLocal()
            cutoff = (datetime.utcnow() - timedelta(seconds=max_age_seconds)).timestamp()
            
            deleted = session.query(PendingScan).filter(
                PendingScan.timestamp < cutoff
            ).delete()
            
            session.commit()
            session.close()
            
            if deleted > 0:
                logger.info(f"[DB] Cleaned up {deleted} old scans")
            return deleted
        except Exception as e:
            logger.error(f"[DB] Failed to cleanup scans: {e}")
            return 0
    
    # ========== REGISTERED FACES ==========
    
    def register_face(self, member_id: int, image_path: str, 
                     image_base64: str = None) -> bool:
        """Register/update face for member."""
        try:
            from models.database import RegisteredFace
            
            session = self.SessionLocal()
            
            # Delete existing if any
            session.query(RegisteredFace).filter(
                RegisteredFace.member_id == member_id
            ).delete()
            
            # Add new
            face = RegisteredFace(
                member_id=member_id,
                image_path=image_path,
                image_base64=image_base64,
            )
            session.add(face)
            session.commit()
            session.close()
            
            logger.info(f"[DB] Registered face for member {member_id}")
            return True
        except Exception as e:
            logger.error(f"[DB] Failed to register face: {e}")
            return False
    
    def get_registered_face(self, member_id: int) -> Optional[Dict]:
        """Get registered face for member."""
        try:
            from models.database import RegisteredFace
            
            session = self.SessionLocal()
            record = session.query(RegisteredFace).filter(
                RegisteredFace.member_id == member_id
            ).first()
            
            if record:
                result = {
                    'member_id': record.member_id,
                    'image_path': record.image_path,
                    'image_base64': record.image_base64,
                    'registered_at': record.registered_at.isoformat() if record.registered_at else None,
                }
                session.close()
                return result
            
            session.close()
            return None
        except Exception as e:
            logger.error(f"[DB] Failed to get registered face: {e}")
            return None
    
    def get_all_registered_faces(self) -> List[Dict]:
        """Get all registered faces."""
        try:
            from models.database import RegisteredFace
            
            session = self.SessionLocal()
            records = session.query(RegisteredFace).all()
            
            faces = []
            for r in records:
                faces.append({
                    'member_id': r.member_id,
                    'image_path': r.image_path,
                    'image_base64': r.image_base64,
                    'registered_at': r.registered_at.isoformat() if r.registered_at else None,
                })
            
            session.close()
            return faces
        except Exception as e:
            logger.error(f"[DB] Failed to get registered faces: {e}")
            return []
    
    # ========== UTILITY METHODS ==========
    
    @staticmethod
    def _dict_to_json(d: dict) -> str:
        """Convert dict to JSON string."""
        import json
        return json.dumps(d)
    
    @staticmethod
    def _json_to_dict(s: str) -> dict:
        """Convert JSON string to dict."""
        import json
        return json.loads(s) if s else {}
