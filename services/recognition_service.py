# ============================================================
# RECOGNITION ENGINE - Face Embedding and Identity Matching
# ============================================================
# Handles:
# - Embedding extraction using ArcFace
# - Similarity search with FAISS
# - Temporal confidence averaging per track
# - Multi-frame confirmation
# - Known vs unknown classification

import logging
import numpy as np
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass
from datetime import datetime, timedelta
import threading

logger = logging.getLogger(__name__)


@dataclass
class RecognitionResult:
    """Result of face recognition."""
    person_id: Optional[int] = None  # None if unknown
    person_name: Optional[str] = None
    confidence: float = 0.0  # 0.0-1.0
    is_stable: bool = False  # True if confirmed across frames
    is_unknown_candidate: bool = False
    unknown_candidate_id: Optional[int] = None
    is_ignored: bool = False
    similarity_score: float = 0.0  # Raw similarity from FAISS
    
    def is_recognized(self) -> bool:
        """True if identity is established."""
        return self.person_id is not None and self.confidence > 0.5


class RecognitionEngine:
    """
    Face recognition engine with:
    - Multi-frame temporal averaging
    - FAISS similarity search
    - Track-based confidence accumulation
    """
    
    def __init__(self, detector, vector_db, db_service=None, 
                 similarity_threshold: float = 0.5,
                 recognition_threshold: float = 0.6):
        """
        Initialize recognition engine.
        
        Args:
            detector: FaceDetector instance (for embeddings)
            vector_db: FAISSVectorDB instance
            db_service: DatabaseService instance
            similarity_threshold: Min similarity for known person match
            recognition_threshold: Min confidence to confirm identity
        """
        self.detector = detector
        self.vector_db = vector_db
        self.db_service = db_service
        self.similarity_threshold = similarity_threshold
        self.recognition_threshold = recognition_threshold
        
        # Track-level confidence accumulation
        self.track_confidence_history: Dict[int, List[float]] = {}
        self.track_embeddings_buffer: Dict[int, List[np.ndarray]] = {}
        self.lock = threading.Lock()
    
    def recognize_track(self, track_id: int, embedding: np.ndarray, 
                       confidence: float) -> RecognitionResult:
        """
        Recognize face from track.
        
        Uses temporal averaging:
        1. Collect embeddings from multiple frames
        2. Average embeddings for better matching
        3. Search FAISS for known person
        4. Return confidence after multi-frame confirmation
        
        Args:
            track_id: Persistent track ID
            embedding: Face embedding (512-dim)
            confidence: Detection confidence
        
        Returns:
            RecognitionResult with identity and confidence
        """
        with self.lock:
            # Store embedding and confidence for this track
            if track_id not in self.track_embeddings_buffer:
                self.track_embeddings_buffer[track_id] = []
                self.track_confidence_history[track_id] = []
            
            self.track_embeddings_buffer[track_id].append(embedding)
            self.track_confidence_history[track_id].append(confidence)
            
            # Keep last 10 embeddings per track
            if len(self.track_embeddings_buffer[track_id]) > 10:
                self.track_embeddings_buffer[track_id].pop(0)
                self.track_confidence_history[track_id].pop(0)
            
            # Average embeddings from buffer
            embeddings = np.array(self.track_embeddings_buffer[track_id])
            avg_embedding = np.mean(embeddings, axis=0)
            
            # Normalize
            norm = np.linalg.norm(avg_embedding)
            if norm > 0:
                avg_embedding = avg_embedding / norm
            
            # Average confidence from buffer
            avg_confidence = np.mean(self.track_confidence_history[track_id])
        
        # Search FAISS for known person
        results = self.vector_db.search(
            avg_embedding, 
            k=5, 
            threshold=self.similarity_threshold
        )
        
        if results:
            person_id, similarity = results[0]
            
            # Get person name if available
            person_name = None
            if self.db_service:
                person_name = self.db_service.get_person_name(person_id)
            
            # Multi-frame confirmation
            num_embeddings = len(self.track_embeddings_buffer[track_id])
            is_stable = num_embeddings >= 3 and similarity > 0.6
            
            # Calculate final confidence
            final_confidence = similarity * avg_confidence
            
            return RecognitionResult(
                person_id=person_id,
                person_name=person_name,
                confidence=final_confidence,
                is_stable=is_stable,
                similarity_score=similarity,
            )
        
        # Unknown person - check if it's a candidate or ignored
        return self._check_unknown(avg_embedding, track_id)
    
    def _check_unknown(self, embedding: np.ndarray, track_id: int) -> RecognitionResult:
        """
        Check if unknown face is a candidate or ignored.
        
        Args:
            embedding: Face embedding
            track_id: Track ID
        
        Returns:
            RecognitionResult with unknown/candidate/ignored status
        """
        # Search unknown candidates
        unknown_results = self.vector_db.search_unknown(
            embedding, 
            k=1, 
            threshold=0.6  # Threshold for unknown face matching
        )
        
        if unknown_results:
            internal_id, similarity, metadata = unknown_results[0]
            candidate_id = metadata.get('candidate_id')
            
            # Check if ignored
            if self.db_service and self.db_service.is_face_ignored(candidate_id):
                return RecognitionResult(
                    is_ignored=True,
                    unknown_candidate_id=candidate_id,
                    confidence=similarity,
                )
            
            return RecognitionResult(
                is_unknown_candidate=True,
                unknown_candidate_id=candidate_id,
                confidence=similarity,
            )
        
        # Completely unknown face
        return RecognitionResult(
            is_unknown_candidate=False,
            confidence=0.0,
        )
    
    def extract_embedding_from_frame(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        Extract embedding from frame.
        
        Args:
            frame: Input frame (BGR)
        
        Returns:
            512-dim face embedding or None if no face
        """
        embedding = self.detector.extract_embedding(frame)
        if embedding is not None:
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
        return embedding
    
    def clear_track_history(self, track_id: int):
        """Clear recognition history for track (when track dies)."""
        with self.lock:
            self.track_confidence_history.pop(track_id, None)
            self.track_embeddings_buffer.pop(track_id, None)
    
    def get_track_confidence_stats(self, track_id: int) -> Dict[str, float]:
        """Get confidence statistics for track."""
        with self.lock:
            if track_id in self.track_confidence_history:
                conf_hist = self.track_confidence_history[track_id]
                return {
                    'mean': np.mean(conf_hist),
                    'min': np.min(conf_hist),
                    'max': np.max(conf_hist),
                    'std': np.std(conf_hist),
                    'samples': len(conf_hist),
                }
            return {}
    
    def get_stats(self) -> dict:
        """Get recognition engine statistics."""
        with self.lock:
            return {
                'tracked_identities': len(self.track_confidence_history),
                'total_embeddings_stored': sum(len(embs) for embs in self.track_embeddings_buffer.values()),
                'vector_db_stats': self.vector_db.get_stats() if self.vector_db else {},
            }
