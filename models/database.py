# ============================================================
# DATABASE MODELS - Core Data Structures
# ============================================================
# SQLAlchemy models for:
# - persons (registered users)
# - face_embeddings (high-quality verified embeddings)
# - attendance_records (check-in/out history)
# - unknown_candidates (passive enrollment)
# - ignored_faces (excluded people)

import json
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass, asdict
import numpy as np


# ============================================================
# DATACLASS MODELS (for in-memory use and API responses)
# ============================================================

@dataclass
class PersonData:
    """Registered person."""
    person_id: int
    name: str
    employee_id: str
    created_at: datetime
    updated_at: datetime
    is_active: bool = True
    metadata: dict = None  # Custom fields

    def to_dict(self):
        d = asdict(self)
        d['created_at'] = self.created_at.isoformat()
        d['updated_at'] = self.updated_at.isoformat()
        return d


@dataclass
class EmbeddingData:
    """Face embedding record."""
    embedding_id: int
    person_id: int
    embedding: np.ndarray  # 512-dim normalized vector
    quality_score: float  # 0.0-1.0
    source: str  # 'manual_enrollment', 'passive_enrollment', 'track'
    face_hash: str  # Unique identifier for this face crop
    created_at: datetime
    frame_index: int = 0  # Track frame when collected

    def embedding_to_list(self) -> list:
        """Convert embedding array to list for JSON."""
        return self.embedding.astype(np.float32).tolist()


@dataclass
class AttendanceRecord:
    """Attendance check-in/out."""
    record_id: int
    person_id: int
    check_in_time: datetime
    check_out_time: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    confidence_avg: float = 0.0  # Average recognition confidence
    track_duration: int = 0  # How long was tracked (ms)
    device: str = 'webcam'
    notes: Optional[str] = None

    def to_dict(self):
        d = asdict(self)
        d['check_in_time'] = self.check_in_time.isoformat()
        if self.check_out_time:
            d['check_out_time'] = self.check_out_time.isoformat()
        return d


@dataclass
class UnknownCandidate:
    """Unknown person being passively enrolled."""
    candidate_id: int
    embedding_cluster_id: str  # Unique hash for this unknown person
    best_face_embedding: np.ndarray  # 512-dim vector
    best_face_image_path: str  # Path to best quality face crop
    best_quality_score: float
    seen_count: int  # How many times detected
    first_seen: datetime
    last_seen: datetime
    avg_quality: float
    is_merged: bool = False
    merged_into_candidate_id: Optional[int] = None
    ignored_until: Optional[datetime] = None  # When ignore expires
    collected_embeddings_count: int = 0
    avg_embedding: Optional[np.ndarray] = None  # Averaged embedding

    def embedding_to_list(self) -> list:
        """Convert embedding to list for JSON."""
        if self.best_face_embedding is not None:
            return self.best_face_embedding.astype(np.float32).tolist()
        return []

    def avg_embedding_to_list(self) -> list:
        """Convert avg embedding to list for JSON."""
        if self.avg_embedding is not None:
            return self.avg_embedding.astype(np.float32).tolist()
        return []


@dataclass
class IgnoredFace:
    """Ignored unknown face."""
    ignored_id: int
    embedding_cluster_id: str
    reason: str
    created_at: datetime
    expires_at: Optional[datetime]
    representative_embedding: np.ndarray


@dataclass
class TrackedFaceData:
    """Current tracked face during live tracking."""
    track_id: int
    person_id: Optional[int] = None  # None if unknown
    confidence: float = 0.0
    last_bbox: tuple = None  # (x1, y1, x2, y2)
    embedding_buffer: List[np.ndarray] = None  # Multiple embeddings for averaging
    embedding_confidence_buffer: List[float] = None
    frame_count: int = 0
    last_seen_frame: int = 0
    recognized_frames: int = 0  # Frames where recognized with confidence
    is_recognized_stable: bool = False

    def __post_init__(self):
        if self.embedding_buffer is None:
            self.embedding_buffer = []
        if self.embedding_confidence_buffer is None:
            self.embedding_confidence_buffer = []


# ============================================================
# DATABASE SCHEMA (SQLAlchemy models)
# ============================================================

try:
    from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, LargeBinary
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import relationship

    Base = declarative_base()

    class Person(Base):
        """Registered person."""
        __tablename__ = 'persons'

        person_id = Column(Integer, primary_key=True)
        name = Column(String(255), nullable=False)
        employee_id = Column(String(100), unique=True, nullable=True)
        created_at = Column(DateTime, default=datetime.utcnow)
        updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
        is_active = Column(Boolean, default=True)
        meta_data = Column(Text, default='{}')  # JSON string (renamed from metadata)

        # Relationships
        embeddings = relationship("FaceEmbedding", back_populates="person", cascade="all, delete-orphan")
        attendance_records = relationship("AttendanceRecord", back_populates="person", cascade="all, delete-orphan")

        def to_data(self) -> PersonData:
            return PersonData(
                person_id=self.person_id,
                name=self.name,
                employee_id=self.employee_id,
                created_at=self.created_at,
                updated_at=self.updated_at,
                is_active=self.is_active,
                metadata=json.loads(self.meta_data) if self.meta_data else {}  # Updated reference
            )


    class FaceEmbedding(Base):
        """Face embedding for registered person."""
        __tablename__ = 'face_embeddings'

        embedding_id = Column(Integer, primary_key=True)
        person_id = Column(Integer, ForeignKey('persons.person_id'), nullable=False)
        embedding = Column(LargeBinary, nullable=False)  # 512-dim float32
        quality_score = Column(Float, default=0.0)  # 0.0-1.0
        source = Column(String(50), default='manual')  # 'manual_enrollment', 'passive_enrollment', 'track'
        face_hash = Column(String(64), unique=True)  # SHA256 hash
        frame_index = Column(Integer, default=0)
        created_at = Column(DateTime, default=datetime.utcnow)

        # Relationship
        person = relationship("Person", back_populates="embeddings")


    class AttendanceRecord(Base):
        """Attendance check-in record."""
        __tablename__ = 'attendance_records'

        record_id = Column(Integer, primary_key=True)
        person_id = Column(Integer, ForeignKey('persons.person_id'), nullable=False)
        check_in_time = Column(DateTime, default=datetime.utcnow)
        check_out_time = Column(DateTime, nullable=True)
        duration_seconds = Column(Integer, nullable=True)
        confidence_avg = Column(Float, default=0.0)
        track_duration = Column(Integer, default=0)  # ms
        device = Column(String(50), default='webcam')
        notes = Column(Text, nullable=True)

        # Relationship
        person = relationship("Person", back_populates="attendance_records")


    class UnknownCandidate(Base):
        """Unknown person being passively enrolled."""
        __tablename__ = 'unknown_candidates'

        candidate_id = Column(Integer, primary_key=True)
        embedding_cluster_id = Column(String(64), unique=True)  # Hash of first embedding
        best_face_embedding = Column(LargeBinary, nullable=False)  # 512-dim float32
        best_face_image_path = Column(String(512))
        best_quality_score = Column(Float, default=0.0)
        seen_count = Column(Integer, default=1)
        first_seen = Column(DateTime, default=datetime.utcnow)
        last_seen = Column(DateTime, default=datetime.utcnow)
        avg_quality = Column(Float, default=0.0)
        is_merged = Column(Boolean, default=False)
        merged_into_candidate_id = Column(Integer, ForeignKey('unknown_candidates.candidate_id'), nullable=True)
        ignored_until = Column(DateTime, nullable=True)
        collected_embeddings_count = Column(Integer, default=1)
        avg_embedding = Column(LargeBinary, nullable=True)  # Averaged embedding


    class IgnoredFace(Base):
        """Ignored unknown face entry."""
        __tablename__ = 'ignored_faces'

        ignored_id = Column(Integer, primary_key=True)
        embedding_cluster_id = Column(String(64), unique=True)
        reason = Column(String(255))
        created_at = Column(DateTime, default=datetime.utcnow)
        expires_at = Column(DateTime, nullable=True)
        representative_embedding = Column(LargeBinary, nullable=False)


    class PendingScan(Base):
        """Pending scan event from backend camera."""
        __tablename__ = 'pending_scans'

        id = Column(String(64), primary_key=True)  # UUID
        member_id = Column(Integer, ForeignKey('persons.person_id'), nullable=True)  # None if unknown
        timestamp = Column(Float, nullable=False)  # Unix timestamp
        image_base64 = Column(Text, nullable=True)  # Base64 encoded image
        recognized = Column(Boolean, default=False)
        confidence = Column(Float, nullable=True)
        face_quality = Column(String(50), nullable=True)
        created_at = Column(DateTime, default=datetime.utcnow)

        # Relationship
        person = relationship("Person", foreign_keys=[member_id])


    class RegisteredFace(Base):
        """Registered face for a person."""
        __tablename__ = 'registered_faces'

        id = Column(Integer, primary_key=True)
        member_id = Column(Integer, ForeignKey('persons.person_id'), nullable=False, unique=True)
        image_path = Column(String(512), nullable=False)
        image_base64 = Column(Text, nullable=True)  # Optional base64 backup
        registered_at = Column(DateTime, default=datetime.utcnow)

        # Relationship
        person = relationship("Person")

except ImportError:
    # SQLAlchemy not required for in-memory operation
    pass


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_database(db_path: str = "face_attendance.db", echo: bool = False):
    """
    Initialize database with schema.

    Args:
        db_path: Path to SQLite database file
        echo: Enable SQL query logging

    Returns:
        (engine, SessionLocal)
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{db_path}", echo=echo)
    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine)
    return engine, SessionLocal


# ============================================================
# DATABASE HELPER FUNCTIONS
# ============================================================

def embedding_to_bytes(embedding: np.ndarray) -> bytes:
    """Convert numpy array to bytes for storage."""
    return embedding.astype(np.float32).tobytes()


def bytes_to_embedding(data: bytes) -> np.ndarray:
    """Convert bytes back to numpy array."""
    return np.frombuffer(data, dtype=np.float32)


def compute_embedding_hash(embedding: np.ndarray) -> str:
    """Compute unique hash for embedding for deduplication."""
    import hashlib
    data = embedding.astype(np.float32).tobytes()
    return hashlib.sha256(data).hexdigest()
