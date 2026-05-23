# ============================================================
# RECOGNIZER MODULE - Embedding Comparison and Identification
# ============================================================
# Handles:
# - Embedding database loading and management
# - Normalized cosine similarity comparison
# - Batch similarity computation
# - Identity voting and confidence aggregation

from typing import Dict, List, Tuple, Optional
import numpy as np
import os
import cv2
from utils.metrics import get_metrics


class FaceRecognizer:
    """
    Recognition engine for face identification via embeddings.
    
    Maintains embedding database and performs:
    - Embedding averaging per person
    - Efficient similarity search
    - Batch comparisons
    - Confidence tracking
    """
    
    def __init__(self, db_path: str, detector=None, normalize: bool = True):
        """
        Initialize recognizer and load face database.
        
        Args:
            db_path: Path to registered_faces directory
            detector: FaceDetector instance for embedding extraction
            normalize: Whether to normalize embeddings
        """
        self.db_path = db_path
        self.detector = detector
        self.normalize = normalize
        self.database: Dict[str, List[np.ndarray]] = {}
        self.database_embeddings: Dict[str, np.ndarray] = {}  # Averaged embeddings
        self.metrics = get_metrics()
        
        self._load_database()
    
    def _load_database(self):
        """Load all embeddings from registered_faces directory."""
        print(f"\n[RECOGNIZER] Loading database from: {os.path.abspath(self.db_path)}")
        
        if not os.path.exists(self.db_path):
            print(f"[ERROR] Database path not found: {self.db_path}")
            print(f"[INFO] Create directory: mkdir -p {self.db_path}")
            return
        
        self.database.clear()
        self.database_embeddings.clear()
        
        valid_extensions = ('.jpg', '.jpeg', '.png')
        total_images = 0
        loaded_faces = 0
        failed_faces = []
        
        for root, _, files in os.walk(self.db_path):
            for file in sorted(files):
                if not file.lower().endswith(valid_extensions):
                    continue
                
                total_images += 1
                img_path = os.path.join(root, file)
                
                # Extract name from directory
                if root != self.db_path:
                    name = os.path.basename(root)
                else:
                    name = os.path.splitext(file)[0]
                
                # Load and extract embedding
                try:
                    embedding = self._extract_embedding_from_file(img_path)
                    if embedding is None:
                        print(f"[SKIP] No face detected in: {file}")
                        failed_faces.append((file, "no face"))
                        continue
                    
                    if name not in self.database:
                        self.database[name] = []
                    
                    self.database[name].append(embedding)
                    loaded_faces += 1
                    print(f"[OK] {name}: {file}")
                
                except Exception as e:
                    print(f"[ERROR] Failed to process {file}: {e}")
                    failed_faces.append((file, str(e)))
        
        # Compute averaged embeddings
        for name, embeddings in self.database.items():
            try:
                emb_array = np.stack(embeddings)
                avg_embedding = np.mean(emb_array, axis=0)
                
                if self.normalize:
                    avg_embedding = avg_embedding / (np.linalg.norm(avg_embedding) + 1e-6)
                
                self.database_embeddings[name] = avg_embedding
            except Exception as e:
                print(f"[ERROR] Failed to compute embedding for {name}: {e}")
        
        print("\n================================================")
        print(f"[SUMMARY] Total: {total_images} | Loaded: {loaded_faces} | People: {len(self.database)}")
        print("================================================\n")
        
        if not self.database:
            print("[WARNING] No faces loaded! Check registered_faces directory structure.")
            print("[INFO] Expected structure:")
            print("  registered_faces/")
            print("    └── person_name/")
            print("        ├── photo1.jpg")
            print("        └── photo2.jpg")
    
    def _extract_embedding_from_file(self, img_path: str) -> Optional[np.ndarray]:
        """Extract embedding from image file."""
        img = cv2.imread(img_path)
        if img is None:
            return None
        
        # Use detector to get embedding
        if not hasattr(self, 'detector') or self.detector is None:
            return None
        
        detections, _ = self.detector.detect(img)
        if not detections or len(detections) == 0:
            return None
        
        # Use first detection
        return detections[0]['embedding']
    
    def identify(self, embedding: np.ndarray, threshold: float = 0.42) -> Tuple[Optional[str], float, Dict]:
        """
        Identify person from embedding via similarity matching.
        
        Production-optimized with better error handling and logging.
        
        Args:
            embedding: Face embedding to identify (should be normalized)
            threshold: Cosine distance threshold (0-2 range, lower = more strict)
                      0.40-0.45 = good for production
                      0.35 = very strict (many false negatives)
                      0.50 = lenient (some false positives)
        
        Returns:
            (name, distance, all_scores_dict) or (None, distance, all_scores_dict)
        """
        self.metrics.start_timer("identify")
        
        # Validate input
        if embedding is None or len(embedding) == 0:
            return None, float('inf'), {}
        
        if not self.database_embeddings:
            print("[WARNING] Database is empty - no faces to match against")
            return None, float('inf'), {}
        
        try:
            # Normalize query embedding
            embedding_norm = np.linalg.norm(embedding)
            if embedding_norm == 0:
                return None, float('inf'), {}
            
            emb = embedding / (embedding_norm + 1e-6)
            
            best_name = None
            best_distance = float('inf')
            all_scores = {}
            second_best_distance = float('inf')
            
            # Compare against all known identities
            for name, db_embedding in self.database_embeddings.items():
                # Cosine similarity
                similarity = np.dot(db_embedding, emb)
                similarity = np.clip(similarity, -1.0, 1.0)
                distance = 1.0 - similarity
                
                all_scores[name] = float(distance)
                
                # Track top 2 matches for confidence estimation
                if distance < best_distance:
                    second_best_distance = best_distance
                    best_distance = distance
                    best_name = name
                elif distance < second_best_distance:
                    second_best_distance = distance
            
            self.metrics.end_timer("identify")
            
            # Decision logic - PRODUCTION OPTIMIZED
            # Accept if:
            # 1. Best match is below threshold AND
            # 2. Gap between top matches is significant (to avoid ambiguity)
            if best_distance < threshold:
                match_gap = second_best_distance - best_distance
                if match_gap > 0.05:  # Clear winner
                    return best_name, best_distance, all_scores
                elif match_gap > 0.02 and best_distance < threshold * 0.9:  # Confident match
                    return best_name, best_distance, all_scores
            
            return None, best_distance, all_scores
        
        except Exception as e:
            print(f"[ERROR] Recognition error: {e}")
            return None, float('inf'), {}
    
    
    def batch_identify(self, embeddings: np.ndarray, 
                      threshold: float = 0.35) -> List[Tuple[Optional[str], float]]:
        """
        Identify multiple faces at once (more efficient).
        
        Args:
            embeddings: [N, 512] embeddings array
            threshold: Distance threshold
        
        Returns:
            List of (name, distance) tuples
        """
        self.metrics.start_timer("batch_identify")
        
        results = []
        
        # Normalize query embeddings
        embeddings = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-6)
        
        # Stack database embeddings
        db_embeddings = np.stack(list(self.database_embeddings.values()))
        db_names = list(self.database_embeddings.keys())
        
        # Batch similarity: [N_queries, N_people]
        similarities = np.dot(embeddings, db_embeddings.T)
        similarities = np.clip(similarities, -1.0, 1.0)
        distances = 1.0 - similarities
        
        # Find best match for each query
        for i, dist_row in enumerate(distances):
            best_idx = np.argmin(dist_row)
            best_distance = float(dist_row[best_idx])
            best_name = db_names[best_idx] if best_distance < threshold else None
            results.append((best_name, best_distance))
        
        self.metrics.end_timer("batch_identify")
        return results
    
    def reload_database(self):
        """Hot reload database (for background refresh)."""
        print("[RECOGNIZER] Reloading database...")
        self._load_database()
        print("[RECOGNIZER] Database reloaded")
