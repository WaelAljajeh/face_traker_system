import numpy as np
from typing import Dict, List, Tuple, Optional


class FaceRecognizer:
    def __init__(self, db_service, vector_db=None, normalize=True):
        """
        DB-based recognizer with FAISS vector database support.
        
        Args:
            db_service: DatabaseService instance for SQLite persistence
            vector_db: FAISSVectorDB instance for fast similarity search
            normalize: L2-normalize embeddings (required for cosine similarity)
        """
        self.db_service = db_service
        self.vector_db = vector_db
        self.normalize = normalize

        # In-memory fallback cache: person_id -> embedding
        self.database: Dict[str, np.ndarray] = {}

        self.load_database()

    # ============================================================
    # LOAD FROM DATABASE -> FAISS
    # ============================================================
    def load_database(self):
        """
        Load embeddings from SQLite and populate FAISS vector DB.
        Clears existing FAISS index before repopulating to avoid duplicates.
        """
        print("[RECOGNIZER] Loading embeddings from database...")

        self.database.clear()
        
        # Reset FAISS index if available
        if self.vector_db:
            self.vector_db.clear()

        rows = []
        try:
            # Try bulk load first
            rows = self.db_service.get_all_embeddings()
        except Exception as e:
            print(f"[RECOGNIZER] Bulk load failed ({e}), falling back to per-person load...")
            # Fallback: load persons individually via SQLAlchemy API
            try:
                persons = self.db_service.get_all_persons()
                for person in persons:
                    pid = person.person_id if hasattr(person, 'person_id') else person.get('person_id')
                    embs = self.db_service.get_embeddings_for_person(pid)
                    for emb in embs:
                        rows.append((pid, emb.tobytes()))
            except Exception as e2:
                print(f"[RECOGNIZER] Fallback load also failed: {e2}")

        if not rows:
            print("[RECOGNIZER] No embeddings found in DB")
            return

        for row in rows:
            # Handle both dict-style and tuple-style rows robustly
            if isinstance(row, dict):
                person_id = row["person_id"]
                embedding_blob = row["embedding"]
            else:
                person_id = row[0]
                embedding_blob = row[1]

            embedding = np.frombuffer(embedding_blob, dtype=np.float32)

            if self.normalize:
                norm = np.linalg.norm(embedding)
                if norm > 0:
                    embedding = embedding / norm

            # Store in memory fallback cache
            self.database[str(person_id)] = embedding
            
            # Add to FAISS vector database for fast search
            if self.vector_db:
                # Ensure person_id is int for FAISS metadata consistency
                pid_for_faiss = int(person_id) if str(person_id).isdigit() else person_id
                self.vector_db.add_embedding(
                    embedding=embedding,
                    person_id=pid_for_faiss,
                    source='database',
                    quality_score=1.0
                )

        print(f"[RECOGNIZER] Loaded {len(self.database)} embeddings into memory cache")
        if self.vector_db:
            stats = self.vector_db.get_stats()
            print(f"[RECOGNIZER] FAISS index ready: {stats.get('total_embeddings', 0)} embeddings, "
                  f"{stats.get('unique_persons', 0)} unique persons")

    # ============================================================
    # EMBEDDING NORMALIZATION
    # ============================================================
    def _normalize(self, emb: np.ndarray) -> np.ndarray:
        if not self.normalize:
            return emb
        norm = np.linalg.norm(emb)
        return emb / (norm + 1e-6) if norm > 0 else emb

    # ============================================================
    # IDENTIFY FACE
    # ============================================================
    def identify(self, embedding: np.ndarray, threshold: float = 0.6):
        """
        Compare face embedding with DB using FAISS vector search.
        Falls back to in-memory linear scan if FAISS is unavailable or empty.
        
        Args:
            embedding: 512-dim face embedding
            threshold: Minimum cosine similarity to declare a match (0.0-1.0)
        
        Returns:
            (result_dict, best_score, all_scores_dict)
        """
        if embedding is None:
            return None, 0.0, {}

        embedding = self._normalize(embedding)

        # Primary path: Use FAISS vector database for fast ANN search
        if self.vector_db and self.vector_db.get_stats().get('total_embeddings', 0) > 0:
            return self._identify_with_faiss(embedding, threshold)
        
        # Fallback path: In-memory linear scan (O(N) brute force)
        if len(self.database) == 0:
            return None, 0.0, {}
            
        return self._identify_in_memory(embedding, threshold)

    def _identify_with_faiss(self, embedding: np.ndarray, threshold: float):
        """
        Fast identification using FAISS approximate nearest neighbor search.
        """
        # Search top-5 nearest neighbors with a generous lower bound
        # so we can populate all_scores from memory cache afterwards
        results = self.vector_db.search(embedding, k=5, threshold=0.4)
        
        all_scores: Dict[str, float] = {}
        best_id: Optional[str] = None
        best_score = -1.0
        
        # Process FAISS results
        for person_id, similarity in results:
            pid_str = str(person_id)
            all_scores[pid_str] = float(similarity)
            if similarity > best_score:
                best_score = similarity
                best_id = pid_str
        
        # Populate remaining scores from memory cache for completeness
        for pid, db_emb in self.database.items():
            if pid not in all_scores:
                score = float(np.dot(embedding, db_emb))
                all_scores[pid] = score
        
        if best_score >= threshold and best_id is not None:
            person = self.db_service.get_person(best_id)
            name = self._extract_name(person)
            return {
                "recognized": True,
                "person_id": best_id,
                "name": name,
                "confidence": float(best_score),
            }, best_score, all_scores
        
        return {
            "recognized": False,
            "person_id": None,
            "name": None,
            "confidence": float(best_score),
        }, best_score, all_scores

    def _identify_in_memory(self, embedding: np.ndarray, threshold: float):
        """
        Fallback linear scan through in-memory database.
        """
        best_id = None
        best_score = -1.0
        all_scores = {}

        for person_id, db_emb in self.database.items():
            score = float(np.dot(embedding, db_emb))
            all_scores[person_id] = score

            if score > best_score:
                best_score = score
                best_id = person_id

        if best_score >= threshold:
            person = self.db_service.get_person(best_id)
            name = self._extract_name(person)
            return {
                "recognized": True,
                "person_id": best_id,
                "name": name,
                "confidence": float(best_score),
            }, best_score, all_scores

        return {
            "recognized": False,
            "person_id": None,
            "name": None,
            "confidence": float(best_score),
        }, best_score, all_scores

    # ============================================================
    # ADD / UPDATE EMBEDDING
    # ============================================================
    def add_embedding(self, person_id: str, embedding: np.ndarray, 
                      quality_score: float = 1.0, source: str = 'manual'):
        """
        Add new embedding to both FAISS index and SQLite database.
        Keeps all storage layers synchronized.
        """
        embedding = self._normalize(embedding)
        
        # Update memory cache
        self.database[person_id] = embedding
        
        # Update FAISS vector database
        if self.vector_db:
            pid_for_faiss = int(person_id) if str(person_id).isdigit() else person_id
            self.vector_db.add_embedding(
                embedding=embedding,
                person_id=pid_for_faiss,
                source=source,
                quality_score=quality_score
            )
        
        # Persist to SQL database
        try:
            self.db_service.save_embedding(
                person_id=int(person_id) if str(person_id).isdigit() else person_id,
                embedding=embedding,
                quality_score=quality_score,
                source=source
            )
        except Exception as e:
            print(f"[RECOGNIZER] Warning: Failed to save embedding to DB: {e}")
        
        print(f"[RECOGNIZER] Added embedding for person {person_id}")

    # ============================================================
    # HELPERS
    # ============================================================
    @staticmethod
    def _extract_name(person) -> Optional[str]:
        """Safely extract name from person object or dict."""
        if person is None:
            return None
        if hasattr(person, 'name'):
            return person.name
        if isinstance(person, dict):
            return person.get('name')
        return None

    # ============================================================
    # REFRESH DATABASE
    # ============================================================
    def reload(self):
        """Reload all embeddings from DB and rebuild FAISS index."""
        self.load_database()