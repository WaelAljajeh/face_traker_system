import numpy as np
from typing import Dict, List, Tuple, Optional


class FaceRecognizer:
    def __init__(self, db_service, vector_db=None, normalize=True):
        self.db_service = db_service
        self.vector_db = vector_db
        self.normalize = normalize
        self.database: Dict[str, np.ndarray] = {}
        self.load_database()

    def load_database(self):
        print("[RECOGNIZER] ========== load_database() START ==========")
        self.database.clear()
        
        if self.vector_db:
            print("[RECOGNIZER] Clearing FAISS index")
            self.vector_db.clear()

        rows = []
        try:
            rows = self.db_service.get_all_embeddings()
            print(f"[RECOGNIZER] Bulk load returned {len(rows)} rows")
        except Exception as e:
            print(f"[RECOGNIZER] Bulk load failed: {e}")
            try:
                persons = self.db_service.get_all_persons()
                print(f"[RECOGNIZER] Fallback: loaded {len(persons)} persons")
                for person in persons:
                    pid = person.person_id if hasattr(person, 'person_id') else person.get('person_id')
                    embs = self.db_service.get_embeddings_for_person(pid)
                    for emb in embs:
                        rows.append((pid, emb.tobytes()))
                print(f"[RECOGNIZER] Fallback produced {len(rows)} total rows")
            except Exception as e2:
                print(f"[RECOGNIZER] Fallback also failed: {e2}")

        if not rows:
            print("[RECOGNIZER] ⚠️ No embeddings found in DB")
            return

        for i, row in enumerate(rows):
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

            self.database[str(person_id)] = embedding
            
            if self.vector_db:
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
            print(f"[RECOGNIZER] FAISS stats: {stats}")
        print("[RECOGNIZER] ========== load_database() END ==========")
        for pid, emb in list(self.database.items())[:3]:
         print(f"[DEBUG] Stored {pid} norm = {np.linalg.norm(emb):.4f}")

    def _normalize(self, emb: np.ndarray) -> np.ndarray:
        if not self.normalize:
            return emb
        norm = np.linalg.norm(emb)
        return emb / (norm + 1e-6) if norm > 0 else emb

    def identify(self, embedding: np.ndarray, threshold: float = 0.6):
        print(f"\n[RECOGNIZER] ========== identify() START ==========")
        print(f"[RECOGNIZER] Input embedding shape: {getattr(embedding, 'shape', 'None')}")
        print(f"[RECOGNIZER] Input embedding norm: {np.linalg.norm(embedding):.4f}")
        print(f"[RECOGNIZER] Threshold: {threshold}")
        print(f"[RECOGNIZER] Memory cache size: {len(self.database)}")
        print(f"[RECOGNIZER] Vector DB present: {self.vector_db is not None}")

        if embedding is None:
            print("[RECOGNIZER] ❌ embedding is None")
            return None, 0.0, {}

        embedding = self._normalize(embedding)
        print(f"[RECOGNIZER] After normalize norm: {np.linalg.norm(embedding):.4f}")

        faiss_count = 0
        if self.vector_db:
            try:
                faiss_count = self.vector_db.get_stats().get('total_embeddings', 0)
                print(f"[RECOGNIZER] FAISS has {faiss_count} embeddings")
            except Exception as e:
                print(f"[RECOGNIZER] FAISS stats error: {e}")

        if self.vector_db and faiss_count > 0:
            print("[RECOGNIZER] Using FAISS path")
            result = self._identify_with_faiss(embedding, threshold)
        else:
            print("[RECOGNIZER] Using in-memory linear scan path")
            result = self._identify_in_memory(embedding, threshold)

        print(f"[RECOGNIZER] ========== identify() END ==========\n")
        return result

    def _identify_with_faiss(self, embedding: np.ndarray, threshold: float):
        print("[RECOGNIZER] --- FAISS search start ---")
        
        # Search with a low threshold to see ALL candidates
        results = self.vector_db.search(embedding, k=5, threshold=0.0)
        print(f"[RECOGNIZER] FAISS raw results (k=5, threshold=0.0): {results}")

        all_scores: Dict[str, float] = {}
        best_id: Optional[str] = None
        best_score = -1.0
        
        for person_id, similarity in results:
            pid_str = str(person_id)
            all_scores[pid_str] = float(similarity)
            print(f"[RECOGNIZER]   FAISS candidate: pid={pid_str}, raw_score={similarity:.6f}")
            if similarity > best_score:
                best_score = similarity
                best_id = pid_str
        
        # Also compute exact dot products from memory for comparison
        print("[RECOGNIZER] Computing exact dot products from memory cache:")
        for pid, db_emb in self.database.items():
            exact_score = float(np.dot(embedding, db_emb))
            all_scores[pid] = exact_score
            marker = " <-- FAISS best" if pid == best_id else ""
            print(f"[RECOGNIZER]   Memory exact: pid={pid}, exact_dot={exact_score:.6f}{marker}")

        print(f"[RECOGNIZER] Best FAISS score: {best_score:.6f}, best_id: {best_id}")
        print(f"[RECOGNIZER] Threshold check: {best_score:.6f} >= {threshold} ? {best_score >= threshold}")

        if best_score >= threshold and best_id is not None:
            person = self.db_service.get_person(best_id)
            name = self._extract_name(person)
            print(f"[RECOGNIZER] ✅ MATCH: id={best_id}, name={name}, score={best_score:.4f}")
            return {
                "recognized": True,
                "person_id": best_id,
                "name": name,
                "confidence": float(best_score),
            }, best_score, all_scores
        
        print(f"[RECOGNIZER] ❌ NO MATCH (best score {best_score:.4f} < {threshold})")
        return {
            "recognized": False,
            "person_id": None,
            "name": None,
            "confidence": float(best_score),
        }, best_score, all_scores

    def _identify_in_memory(self, embedding: np.ndarray, threshold: float):
        print("[RECOGNIZER] --- In-memory linear scan start ---")
        best_id = None
        best_score = -1.0
        all_scores = {}

        for person_id, db_emb in self.database.items():
            score = float(np.dot(embedding, db_emb))
            all_scores[person_id] = score
            status = ""
            if score > best_score:
                best_score = score
                best_id = person_id
                status = " [NEW BEST]"
            print(f"[RECOGNIZER]   pid={person_id}, score={score:.6f}{status}")

        print(f"[RECOGNIZER] Best memory score: {best_score:.6f}, best_id: {best_id}")
        print(f"[RECOGNIZER] Threshold check: {best_score:.6f} >= {threshold} ? {best_score >= threshold}")

        if best_score >= threshold:
            person = self.db_service.get_person(best_id)
            name = self._extract_name(person)
            print(f"[RECOGNIZER] ✅ MATCH: id={best_id}, name={name}, score={best_score:.4f}")
            return {
                "recognized": True,
                "person_id": best_id,
                "name": name,
                "confidence": float(best_score),
            }, best_score, all_scores

        print(f"[RECOGNIZER] ❌ NO MATCH (best score {best_score:.4f} < {threshold})")
        return {
            "recognized": False,
            "person_id": None,
            "name": None,
            "confidence": float(best_score),
        }, best_score, all_scores

    def add_embedding(self, person_id: str, embedding: np.ndarray, 
                      quality_score: float = 1.0, source: str = 'manual'):
        print(f"\n[RECOGNIZER] ========== add_embedding() START ==========")
        print(f"[RECOGNIZER] Adding for person_id={person_id}, source={source}")
        print(f"[RECOGNIZER] Input embedding shape: {embedding.shape}, norm: {np.linalg.norm(embedding):.4f}")

        embedding = self._normalize(embedding)
        print(f"[RECOGNIZER] After normalize norm: {np.linalg.norm(embedding):.4f}")

        self.database[person_id] = embedding
        
        if self.vector_db:
            pid_for_faiss = int(person_id) if str(person_id).isdigit() else person_id
            self.vector_db.add_embedding(
                embedding=embedding,
                person_id=pid_for_faiss,
                source=source,
                quality_score=quality_score
            )
            print(f"[RECOGNIZER] Added to FAISS, new stats: {self.vector_db.get_stats()}")
        
        try:
            self.db_service.save_embedding(
                person_id=int(person_id) if str(person_id).isdigit() else person_id,
                embedding=embedding,
                quality_score=quality_score,
                source=source
            )
            print("[RECOGNIZER] Saved to SQLite DB")
        except Exception as e:
            print(f"[RECOGNIZER] Warning: DB save failed: {e}")
        
        print(f"[RECOGNIZER] ========== add_embedding() END ==========\n")

    @staticmethod
    def _extract_name(person) -> Optional[str]:
        if person is None:
            return None
        if hasattr(person, 'name'):
            return person.name
        if isinstance(person, dict):
            return person.get('name')
        return None

    def reload(self):
        print("[RECOGNIZER] reload() called")
        self.load_database()