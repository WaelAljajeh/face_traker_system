# ============================================================
# BYTETRACK - Multi-Object Tracking
# ============================================================
# Implements ByteTrack for persistent face tracking across frames.
# Assigns stable track IDs to each face.
#
# Reference: ByteTrack: Multi-Object Tracking by Associating Every Detection Box
# https://arxiv.org/abs/2110.06864

import numpy as np
from typing import List, Dict, Tuple
from dataclasses import dataclass
import time


@dataclass
class Detection:
    """Detection object for ByteTrack."""
    bbox: np.ndarray  # [x1, y1, x2, y2]
    confidence: float
    embedding: np.ndarray


class STrack:
    """Single object track in ByteTrack."""
    
    track_id_counter = 1
    
    def __init__(self, bbox: np.ndarray, confidence: float, embedding: np.ndarray):
        self.track_id = STrack.track_id_counter
        STrack.track_id_counter += 1
        
        self.bbox = bbox.copy()
        self.confidence = confidence
        self.embedding = embedding
        
        self.time_since_update = 0
        self.hits = 0
        self.age = 0
        self.features = [embedding]
    
    def predict(self):
        """Simple constant velocity motion model."""
        self.age += 1
        self.time_since_update += 1
    
    def update(self, detection: Detection):
        """Update track with new detection."""
        self.bbox = detection.bbox.copy()
        self.confidence = detection.confidence
        self.embedding = detection.embedding
        self.features.append(detection.embedding)
        if len(self.features) > 10:
            self.features.pop(0)
        
        self.hits += 1
        self.time_since_update = 0
    
    def get_embedding(self) -> np.ndarray:
        """Get averaged embedding from history."""
        if self.features:
            return np.mean(np.stack(self.features), axis=0)
        return self.embedding
    
    def is_activated(self) -> bool:
        """Track is activated if it has hits."""
        return self.hits > 0


class ByteTrack:
    """
    ByteTrack implementation for multi-face tracking.
    
    Assigns persistent track IDs to detected faces.
    """
    
    def __init__(self, track_high_thresh: float = 0.6,
                 track_low_thresh: float = 0.1,
                 new_track_thresh: float = 0.7,
                 track_buffer: int = 30,
                 match_thresh: float = 0.8):
        """
        Initialize ByteTrack.
        
        Args:
            track_high_thresh: High confidence threshold
            track_low_thresh: Low confidence threshold
            new_track_thresh: Min confidence for new track
            track_buffer: Max frames to keep track
            match_thresh: IOU threshold for matching
        """
        self.track_high_thresh = track_high_thresh
        self.track_low_thresh = track_low_thresh
        self.new_track_thresh = new_track_thresh
        self.track_buffer = track_buffer
        self.match_thresh = match_thresh
        
        self.tracks: List[STrack] = []
        self.lost_tracks: List[STrack] = []
        self.frame_id = 0
    
    def update(self, detections: List[Detection]) -> List[STrack]:
        """
        Update tracks with new detections.
        
        Args:
            detections: List of Detection objects
        
        Returns:
            List of confirmed tracks with IDs
        """
        self.frame_id += 1
        
        # Step 1: Separate detections by confidence
        high_conf = [d for d in detections if d.confidence > self.track_high_thresh]
        low_conf = [d for d in detections if self.track_low_thresh < d.confidence <= self.track_high_thresh]
        
        # Step 2: Match high-confidence detections to existing tracks
        matched_tracks = self._match_detections_to_tracks(high_conf)
        
        # Step 3: Match low-confidence detections to lost tracks
        remaining_low = self._match_low_detections(low_conf)
        
        # Step 4: Create new tracks from unmatched high-confidence detections
        for det in high_conf:
            if det not in [m[1] for m in matched_tracks]:
                track = STrack(det.bbox, det.confidence, det.embedding)
                self.tracks.append(track)
        
        # Step 5: Prune old tracks
        self._prune_tracks()
        
        return self._get_confirmed_tracks()
    
    def _match_detections_to_tracks(self, detections: List[Detection]) -> List[Tuple[STrack, Detection]]:
        """Match detections to existing tracks using IoU and embedding similarity."""
        matched = []
        used_dets = set()
        
        for track in self.tracks:
            if track.time_since_update > self.track_buffer:
                continue
            
            best_score = 0
            best_det = None
            best_idx = -1
            
            for i, det in enumerate(detections):
                if i in used_dets:
                    continue
                
                # Combine IoU and embedding similarity
                iou = self._bbox_iou(track.bbox, det.bbox)
                
                # Embedding similarity (cosine distance)
                emb_sim = np.dot(track.embedding, det.embedding)
                emb_sim = np.clip(emb_sim, -1.0, 1.0)
                
                # Combined score: weighted average of IoU and embedding similarity
                # IoU weight: 0.6, Embedding weight: 0.4 (embeddings more reliable)
                combined_score = 0.4 * iou + 0.6 * emb_sim
                
                # Match if combined score is good OR if IoU is reasonable
                if (combined_score > best_score) and (iou > self.match_thresh * 0.5 or emb_sim > 0.7):
                    best_score = combined_score
                    best_det = det
                    best_idx = i
            
            if best_det is not None:
                track.update(best_det)
                matched.append((track, best_det))
                used_dets.add(best_idx)
        
        return matched
    
    def _match_low_detections(self, detections: List[Detection]):
        """Match low-confidence detections to lost tracks using IoU and embedding."""
        used_dets = set()
        
        for track in self.lost_tracks:
            if track.time_since_update > self.track_buffer:
                continue
            
            best_score = 0
            best_det = None
            best_idx = -1
            
            for i, det in enumerate(detections):
                if i in used_dets:
                    continue
                
                # Combine IoU and embedding similarity
                iou = self._bbox_iou(track.bbox, det.bbox)
                
                # Embedding similarity (cosine distance)
                emb_sim = np.dot(track.embedding, det.embedding)
                emb_sim = np.clip(emb_sim, -1.0, 1.0)
                
                # Combined score
                combined_score = 0.4 * iou + 0.6 * emb_sim
                
                if (combined_score > best_score) and (iou > self.match_thresh * 0.5 or emb_sim > 0.7):
                    best_score = combined_score
                    best_det = det
                    best_idx = i
            
            if best_det is not None:
                track.update(best_det)
                self.tracks.append(track)
                self.lost_tracks.remove(track)
                used_dets.add(best_idx)
    
    def _prune_tracks(self):
        """Remove dead tracks."""
        # Move expired tracks to lost (keep for 2 seconds = 60 frames @ 30fps)
        new_tracks = []
        for track in self.tracks:
            if track.time_since_update > 2:  # Increased from 1 to 2
                self.lost_tracks.append(track)
            else:
                new_tracks.append(track)
        self.tracks = new_tracks
        
        # Remove very old lost tracks
        self.lost_tracks = [t for t in self.lost_tracks 
                           if t.time_since_update < self.track_buffer]
    
    def _get_confirmed_tracks(self) -> List[STrack]:
        """Return confirmed (activated) tracks."""
        return [t for t in self.tracks if t.is_activated()]
    
    @staticmethod
    def _bbox_iou(box1: np.ndarray, box2: np.ndarray) -> float:
        """Calculate IoU between two boxes."""
        x1_min, y1_min, x1_max, y1_max = box1
        x2_min, y2_min, x2_max, y2_max = box2
        
        inter_xmin = max(x1_min, x2_min)
        inter_ymin = max(y1_min, y2_min)
        inter_xmax = min(x1_max, x2_max)
        inter_ymax = min(y1_max, y2_max)
        
        if inter_xmax < inter_xmin or inter_ymax < inter_ymin:
            return 0.0
        
        inter_area = (inter_xmax - inter_xmin) * (inter_ymax - inter_ymin)
        box1_area = (x1_max - x1_min) * (y1_max - y1_min)
        box2_area = (x2_max - x2_min) * (y2_max - y2_min)
        union_area = box1_area + box2_area - inter_area
        
        return float(inter_area / union_area) if union_area > 0 else 0.0
