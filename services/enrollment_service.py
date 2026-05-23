# ============================================================
# ENROLLMENT SERVICE - Unknown Candidate Management
# ============================================================
# Handles:
# - Passive enrollment of unknown faces
# - Embedding collection and averaging
# - Unknown candidate merging (deduplication)
# - Ignore system for excluded faces
# - Best face image selection

import logging
import os
import cv2
import numpy as np
import hashlib
from typing import Optional, List, Tuple
from datetime import datetime, timedelta
import threading

logger = logging.getLogger(__name__)


class EnrollmentService:
    """
    Manages passive enrollment of unknown faces.
    
    Features:
    - Collects multiple high-quality samples per unknown person
    - Merges duplicate unknown persons using embedding similarity
    - Maintains best face image per candidate
    - Implements ignore system for excluded people
    """
    
    def __init__(self, db_service, vector_db, 
                 unknown_dir: str = './unknown_faces',
                 min_quality_for_enrollment: float = 0.7,
                 enrollment_threshold: float = 0.65,
                 merge_threshold: float = 0.75,
                 ignore_expiry_days: int = 30):
        """
        Initialize enrollment service.
        
        Args:
            db_service: DatabaseService instance
            vector_db: FAISSVectorDB instance
            unknown_dir: Directory to save unknown face images
            min_quality_for_enrollment: Min quality score to enroll
            enrollment_threshold: Similarity threshold for new unknown candidate
            merge_threshold: Similarity threshold for merging candidates
            ignore_expiry_days: Days before ignore entries expire
        """
        self.db_service = db_service
        self.vector_db = vector_db
        self.unknown_dir = unknown_dir
        self.min_quality_for_enrollment = min_quality_for_enrollment
        self.enrollment_threshold = enrollment_threshold
        self.merge_threshold = merge_threshold
        self.ignore_expiry_days = ignore_expiry_days
        
        os.makedirs(unknown_dir, exist_ok=True)
        self.lock = threading.Lock()
    
    def enroll_unknown_face(self, embedding: np.ndarray, face_crop: np.ndarray,
                            quality_score: float, frame_num: int = 0) -> Optional[int]:
        """
        Enroll unknown face for passive enrollment.
        
        Args:
            embedding: 512-dim face embedding
            face_crop: Face image crop (BGR)
            quality_score: Quality score (0.0-1.0)
            frame_num: Frame number where detected
        
        Returns:
            candidate_id or None if not enrolled
        """
        # Only enroll high-quality faces
        if quality_score < self.min_quality_for_enrollment:
            logger.debug(f"[ENROLLMENT] Skipping low-quality face (quality={quality_score:.3f})")
            return None
        
        # Compute embedding hash for this unknown person
        embedding_hash = self._hash_embedding(embedding)
        
        # Check if this embedding matches existing unknown candidate
        existing_candidate = self._find_matching_candidate(embedding, embedding_hash)
        
        if existing_candidate:
            candidate_id = existing_candidate
            logger.debug(f"[ENROLLMENT] Matched to existing candidate {candidate_id}")
        else:
            # Create new unknown candidate
            candidate_id = self._create_unknown_candidate(embedding, face_crop, 
                                                          quality_score, embedding_hash)
            logger.debug(f"[ENROLLMENT] Created new candidate {candidate_id}")
        
        # Update candidate with this face
        self._update_candidate(candidate_id, embedding, face_crop, quality_score)
        
        # Try to merge similar candidates
        self._try_merge_candidates(candidate_id)
        
        return candidate_id
    
    def _find_matching_candidate(self, embedding: np.ndarray, 
                                 embedding_hash: str) -> Optional[int]:
        """
        Find if embedding matches existing unknown candidate.
        
        Args:
            embedding: Face embedding
            embedding_hash: Hash of embedding for quick lookup
        
        Returns:
            candidate_id or None
        """
        # Search FAISS for similar embeddings
        results = self.vector_db.search_unknown(
            embedding,
            k=3,
            threshold=self.enrollment_threshold
        )
        
        if results:
            # Return ID of most similar match
            internal_id, similarity, metadata = results[0]
            logger.debug(f"[ENROLLMENT] Found match with similarity={similarity:.3f}")
            return metadata.get('candidate_id')
        
        return None
    
    def _create_unknown_candidate(self, embedding: np.ndarray, 
                                  face_crop: np.ndarray,
                                  quality_score: float,
                                  embedding_hash: str) -> int:
        """
        Create new unknown candidate.
        
        Args:
            embedding: Face embedding
            face_crop: Face image
            quality_score: Quality score
            embedding_hash: Embedding hash
        
        Returns:
            candidate_id
        """
        timestamp = datetime.now().isoformat()
        face_filename = f"unknown_{embedding_hash[:16]}_{timestamp.replace(':', '_')}.jpg"
        face_path = os.path.join(self.unknown_dir, face_filename)
        
        # Save face image
        cv2.imwrite(face_path, face_crop)
        
        # Create database entry
        candidate_id = self.db_service.create_unknown_candidate(
            embedding=embedding,
            face_image_path=face_path,
            quality_score=quality_score,
            embedding_hash=embedding_hash,
            embedding_cluster_id=embedding_hash,
        )
        
        # Add to vector database
        self.vector_db.add_embedding(
            embedding,
            person_id=-candidate_id,  # Negative ID for unknown candidates
            source='passive_enrollment',
            quality_score=quality_score,
            face_hash=embedding_hash,
        )
        
        return candidate_id
    
    def _update_candidate(self, candidate_id: int, embedding: np.ndarray,
                          face_crop: np.ndarray, quality_score: float):
        """
        Update candidate with new sample.
        
        Tracks:
        - Increased seen count
        - Average quality
        - Best face image
        - Averaged embedding
        """
        # Get current candidate data
        candidate = self.db_service.get_unknown_candidate(candidate_id)
        
        if candidate:
            # Update seen count and timestamps
            new_seen_count = candidate.seen_count + 1
            
            # Update best face if this is higher quality
            if quality_score > candidate.best_quality_score:
                # Save new best face image
                timestamp = datetime.now().isoformat()
                face_filename = f"best_unknown_{candidate_id}_{timestamp.replace(':', '_')}.jpg"
                best_face_path = os.path.join(self.unknown_dir, face_filename)
                cv2.imwrite(best_face_path, face_crop)
                
                best_quality = quality_score
                best_embedding = embedding
                best_image_path = best_face_path
            else:
                best_quality = candidate.best_quality_score
                best_embedding = candidate.best_face_embedding
                best_image_path = candidate.best_face_image_path
            
            # Update average embedding
            current_embeddings = [candidate.best_face_embedding]
            if candidate.avg_embedding is not None:
                current_embeddings.append(candidate.avg_embedding)
            current_embeddings.append(embedding)
            avg_embedding = np.mean(current_embeddings, axis=0)
            
            # Normalize
            norm = np.linalg.norm(avg_embedding)
            if norm > 0:
                avg_embedding = avg_embedding / norm
            
            # Update average quality
            avg_quality = (candidate.avg_quality * (new_seen_count - 1) + quality_score) / new_seen_count
            
            # Update database
            self.db_service.update_unknown_candidate(
                candidate_id,
                seen_count=new_seen_count,
                last_seen=datetime.now(),
                avg_quality=avg_quality,
                best_quality_score=best_quality,
                best_embedding=best_embedding,
                best_image_path=best_image_path,
                avg_embedding=avg_embedding,
                collected_embeddings_count=new_seen_count,
            )
    
    def _try_merge_candidates(self, candidate_id: int):
        """
        Try to merge similar unknown candidates.
        
        Searches for other candidates with very similar embeddings
        and merges them to avoid duplicates.
        """
        candidate = self.db_service.get_unknown_candidate(candidate_id)
        if not candidate or candidate.best_face_embedding is None:
            return
        
        # Search for similar candidates
        results = self.vector_db.search_unknown(
            candidate.avg_embedding or candidate.best_face_embedding,
            k=5,
            threshold=self.merge_threshold
        )
        
        merged_count = 0
        for internal_id, similarity, metadata in results:
            other_candidate_id = metadata.get('candidate_id')
            if other_candidate_id and other_candidate_id != candidate_id:
                # Merge other candidate into this one
                logger.info(f"[ENROLLMENT] Merging candidates {other_candidate_id} -> {candidate_id} (sim={similarity:.3f})")
                self._merge_candidates(candidate_id, other_candidate_id)
                merged_count += 1
        
        if merged_count > 0:
            logger.info(f"[ENROLLMENT] Merged {merged_count} duplicate candidates into {candidate_id}")
    
    def _merge_candidates(self, target_id: int, source_id: int):
        """
        Merge source candidate into target candidate.
        
        Target candidate gets:
        - Higher seen count
        - Best face from both
        - Averaged embeddings from both
        """
        target = self.db_service.get_unknown_candidate(target_id)
        source = self.db_service.get_unknown_candidate(source_id)
        
        if not target or not source:
            return
        
        # Combine statistics
        new_seen_count = target.seen_count + source.seen_count
        avg_quality = (target.avg_quality * target.seen_count + 
                       source.avg_quality * source.seen_count) / new_seen_count
        
        # Select best face
        if source.best_quality_score > target.best_quality_score:
            best_quality = source.best_quality_score
            best_embedding = source.best_face_embedding
            best_image_path = source.best_face_image_path
        else:
            best_quality = target.best_quality_score
            best_embedding = target.best_face_embedding
            best_image_path = target.best_face_image_path
        
        # Average embeddings
        embeddings = [target.best_face_embedding, source.best_face_embedding]
        if target.avg_embedding is not None:
            embeddings.append(target.avg_embedding)
        if source.avg_embedding is not None:
            embeddings.append(source.avg_embedding)
        
        avg_embedding = np.mean(embeddings, axis=0)
        norm = np.linalg.norm(avg_embedding)
        if norm > 0:
            avg_embedding = avg_embedding / norm
        
        # Update target
        self.db_service.update_unknown_candidate(
            target_id,
            seen_count=new_seen_count,
            avg_quality=avg_quality,
            best_quality_score=best_quality,
            best_embedding=best_embedding,
            best_image_path=best_image_path,
            avg_embedding=avg_embedding,
            collected_embeddings_count=new_seen_count,
        )
        
        # Mark source as merged
        self.db_service.mark_candidate_merged(source_id, target_id)
    
    def ignore_face(self, candidate_id: int, reason: str = "user_decision",
                    days_to_expire: Optional[int] = None) -> bool:
        """
        Mark unknown candidate as ignored.
        
        Ignored faces won't trigger enrollment anymore.
        """
        if days_to_expire is None:
            days_to_expire = self.ignore_expiry_days
        
        expires_at = datetime.now() + timedelta(days=days_to_expire)
        
        candidate = self.db_service.get_unknown_candidate(candidate_id)
        if candidate:
            embedding = candidate.avg_embedding or candidate.best_face_embedding
            result = self.db_service.create_ignored_face(
                embedding_cluster_id=candidate.embedding_cluster_id,
                reason=reason,
                expires_at=expires_at,
                embedding=embedding,
            )
            
            if result:
                logger.info(f"[ENROLLMENT] Ignored face {candidate_id} until {expires_at}")
                return True
        
        return False
    
    def unignore_face(self, candidate_id: int) -> bool:
        """Remove ignore status from candidate."""
        candidate = self.db_service.get_unknown_candidate(candidate_id)
        if candidate:
            return self.db_service.remove_ignored_face(candidate.embedding_cluster_id)
        return False
    
    @staticmethod
    def _hash_embedding(embedding: np.ndarray) -> str:
        """Create unique hash for embedding."""
        data = embedding.astype(np.float32).tobytes()
        return hashlib.sha256(data).hexdigest()
    
    def get_candidates_ready_for_enrollment(self, min_samples: int = 5,
                                            min_avg_quality: float = 0.75) -> List[int]:
        """
        Get unknown candidates that are ready for conversion to person.
        
        Ready if:
        - Seen at least min_samples times
        - Average quality >= min_avg_quality
        - Not ignored
        """
        candidates = self.db_service.get_all_unknown_candidates()
        ready = []
        
        for candidate in candidates:
            if (candidate.seen_count >= min_samples and 
                candidate.avg_quality >= min_avg_quality and 
                not candidate.ignored_until):
                ready.append(candidate.candidate_id)
        
        return ready
    
    def get_stats(self) -> dict:
        """Get enrollment statistics."""
        candidates = self.db_service.get_all_unknown_candidates()
        
        total_candidates = len(candidates)
        total_samples = sum(c.seen_count for c in candidates)
        merged_candidates = sum(1 for c in candidates if c.is_merged)
        ignored_candidates = sum(1 for c in candidates if c.ignored_until)
        
        return {
            'total_unknown_candidates': total_candidates,
            'total_samples_collected': total_samples,
            'merged_candidates': merged_candidates,
            'ignored_candidates': ignored_candidates,
            'ready_for_enrollment': len(self.get_candidates_ready_for_enrollment()),
        }
