# ============================================================
# TRACKED FACE MODEL
# ============================================================
# Represents a single face being tracked across frames with:
# - persistent track ID
# - recognition history
# - temporal aggregation state
# - cooldown management
# - quality and liveness tracking

import time
from typing import Optional, List
import numpy as np
from collections import deque


class TrackedFace:
    """
    Represents a single person being tracked across frames.
    
    Maintains:
    - Track ID (persistent across frames)
    - Bounding box history
    - Face embedding history
    - Recognition history (frame-level votes)
    - Quality and liveness scores
    - Per-face cooldown state
    """
    
    def __init__(self, track_id: int, bbox, embedding: np.ndarray, 
                 quality_score: float = 1.0, liveness_score: float = 1.0):
        """
        Initialize a tracked face.
        
        Args:
            track_id: Unique persistent ID
            bbox: [x1, y1, x2, y2] bounding box
            embedding: Face embedding (normalized)
            quality_score: Initial quality score
            liveness_score: Initial liveness score
        """
        self.track_id = track_id
        self.created_at = time.time()
        self.last_seen = time.time()
        self.frame_count = 0
        
        # Bounding boxes (latest)
        self.current_bbox = bbox
        self.bbox_history = deque([bbox], maxlen=10)
        
        # Embeddings (for averaging)
        self.embedding = embedding if embedding is not None else np.zeros(512)
        self.embedding_history = deque([embedding] if embedding is not None else [np.zeros(512)], maxlen=20)
        
        # Recognition state
        self.recognized_name: Optional[str] = None
        self.identity_votes: dict = {}  # {name: count}
        self.similarity_scores: deque = deque(maxlen=10)  # Rolling window of top similarities
        self.confidence_history: deque = deque(maxlen=10)  # Rolling confidence scores
        
        # Quality and liveness
        self.quality_score = quality_score
        self.quality_history = deque([quality_score], maxlen=10)
        self.liveness_score = liveness_score
        self.liveness_votes = 0  # Count of frames passing liveness
        self.liveness_frames_required = 3
        
        # Scan state
        self.last_scan_time = 0.0
        self.scan_cooldown = 8.0
        self.scan_sent = False
        
        # Temporal confirmation state
        self.stable_frames = 0
        self.min_stable_frames = 1        # Quick recognition (will be updated from config)
        self.is_identity_stable = False
    
    def update(self, bbox, embedding: Optional[np.ndarray] = None, 
               quality_score: float = 1.0, liveness_score: float = 1.0):
        """
        Update track with new detection.
        
        Args:
            bbox: New bounding box
            embedding: New face embedding (optional)
            quality_score: Face quality assessment
            liveness_score: Face liveness score
        """
        self.current_bbox = bbox
        self.bbox_history.append(bbox)
        
        if embedding is not None:
            self.embedding_history.append(embedding)
            # Update moving average embedding
            self._update_average_embedding()
        
        self.quality_score = quality_score
        self.quality_history.append(quality_score)
        
        self.liveness_score = liveness_score
        if liveness_score > 0.5:  # Simple threshold
            self.liveness_votes += 1
        
        self.last_seen = time.time()
        self.frame_count += 1
    
    def _update_average_embedding(self):
        """Update the averaged embedding from history."""
        if self.embedding_history:
            embeddings = np.array(list(self.embedding_history))
            self.embedding = np.mean(embeddings, axis=0)
            # Renormalize
            norm = np.linalg.norm(self.embedding)
            if norm > 0:
                self.embedding = self.embedding / norm
    
    def record_recognition(self, name: str, similarity: float, confidence: float):
        """
        Record a recognition result.
        
        Args:
            name: Identified person name
            similarity: Cosine similarity score
            confidence: Recognition confidence (0-1)
        """
        # Vote for identity
        self.identity_votes[name] = self.identity_votes.get(name, 0) + 1
        
        # Record similarity and confidence
        self.similarity_scores.append(similarity)
        self.confidence_history.append(confidence)
        
        # Check if identity is stable
        self._check_temporal_stability()
    
    def _check_temporal_stability(self):
        """Check if recognized identity is stable across frames."""
        if not self.confidence_history:
            return
        
        # Get majority vote
        if not self.identity_votes:
            self.is_identity_stable = False
            self.stable_frames = 0
            return
        
        majority_name = max(self.identity_votes, key=self.identity_votes.get)
        majority_count = self.identity_votes[majority_name]
        
        # Check if stable
        total_votes = sum(self.identity_votes.values())
        if majority_count >= self.min_stable_frames and majority_count / total_votes > 0.7:
            # Stable: same person consistently recognized
            self.recognized_name = majority_name
            self.stable_frames = majority_count
            self.is_identity_stable = True
        else:
            self.stable_frames = 0
            self.is_identity_stable = False
    
    def get_average_confidence(self) -> float:
        """Get average confidence across history."""
        if not self.confidence_history:
            return 0.0
        return float(np.mean(list(self.confidence_history)))
    
    def get_average_similarity(self) -> float:
        """Get average similarity across history."""
        if not self.similarity_scores:
            return 1.0  # Max distance
        return float(np.mean(list(self.similarity_scores)))
    
    def get_average_quality(self) -> float:
        """Get average quality score."""
        if not self.quality_history:
            return 1.0
        return float(np.mean(list(self.quality_history)))
    
    def is_ready_for_scan(self, current_time: float) -> bool:
        """Check if face is ready to send attendance scan."""
        # Check cooldown
        if current_time - self.last_scan_time < self.scan_cooldown:
            return False
        
        # For known people: require recognition (not necessarily stable yet)
        if self.recognized_name:
            return True
        
        # For unknown faces: minimal check (just require being seen)
        return self.frame_count > 0
    
    def mark_scanned(self, current_time: float):
        """Mark that attendance scan was sent."""
        self.last_scan_time = current_time
        self.scan_sent = True
        self.identity_votes.clear()  # Reset votes after sending
    
    def get_smooth_bbox(self) -> np.ndarray:
        """Get smoothed bounding box from history (simple average)."""
        if self.bbox_history:
            bboxes = np.array(list(self.bbox_history))
            return np.mean(bboxes, axis=0)
        return self.current_bbox
    
    def is_expired(self, current_time: float, max_age: float = 3.0) -> bool:
        """Check if track should be removed (not seen for too long)."""
        return (current_time - self.last_seen) > max_age
    
    def reset_voting(self):
        """Reset identity voting for a new recognition cycle."""
        self.identity_votes.clear()
        self.stable_frames = 0
        self.is_identity_stable = False
