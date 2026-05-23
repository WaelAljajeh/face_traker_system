# ============================================================
# FAISS VECTOR DATABASE - Embedding Storage and Search
# ============================================================
# High-performance similarity search for face embeddings using FAISS.
# Supports:
# - Adding embeddings with person association
# - Similarity search (top-k nearest neighbors)
# - Embedding merging and deduplication
# - Save/load index

import os
import pickle
import logging
import numpy as np
from typing import List, Tuple, Optional
import threading
import hashlib

logger = logging.getLogger(__name__)


class FAISSVectorDB:
    """
    FAISS-based vector database for face embeddings.
    
    Maintains:
    - FAISS index for fast similarity search
    - ID -> person_id mapping
    - Metadata for each embedding
    """
    
    def __init__(self, embedding_dim: int = 512, index_type: str = 'flat', metric: str = 'cosine'):
        """
        Initialize FAISS index.
        
        Args:
            embedding_dim: Embedding dimensionality (512 for ArcFace)
            index_type: 'flat' (exact search) or 'ivf' (approximate, faster for large scale)
            metric: 'cosine' or 'l2'
        """
        try:
            import faiss
            self.faiss = faiss
        except ImportError:
            raise ImportError("FAISS not installed. Install with: pip install faiss-cpu")
        
        self.embedding_dim = embedding_dim
        self.index_type = index_type
        self.metric = metric
        self.lock = threading.Lock()
        
        # Initialize index
        if index_type == 'flat':
            if metric == 'cosine':
                # For cosine, use L2 on normalized vectors
                self.index = faiss.IndexFlatL2(embedding_dim)
            else:
                self.index = faiss.IndexFlatL2(embedding_dim)
        elif index_type == 'ivf':
            # IVF (Inverted File) for faster search on large datasets
            nlist = 100  # Number of Voronoi cells
            quantizer = faiss.IndexFlatL2(embedding_dim)
            self.index = faiss.IndexIVFFlat(quantizer, embedding_dim, nlist)
        else:
            raise ValueError(f"Unknown index type: {index_type}")
        
        # Metadata mapping: internal_id -> (person_id, source, quality_score)
        self.id_to_person = {}  # internal_id -> person_id
        self.id_to_metadata = {}  # internal_id -> {'source', 'quality', 'hash', ...}
        self.next_id = 0
        
        logger.info(f"[FAISS] Initialized {index_type} index (dim={embedding_dim}, metric={metric})")
    
    def add_embedding(self, embedding: np.ndarray, person_id: int, 
                      source: str = 'manual', quality_score: float = 1.0,
                      face_hash: str = None) -> int:
        """
        Add embedding to index.
        
        Args:
            embedding: 512-dim face embedding (should be normalized for cosine)
            person_id: Associated person ID
            source: Where embedding came from
            quality_score: Quality score (0.0-1.0)
            face_hash: Optional unique hash for deduplication
        
        Returns:
            Internal ID in index
        """
        with self.lock:
            embedding = embedding.astype(np.float32)
            
            # Normalize for cosine similarity
            if self.metric == 'cosine':
                norm = np.linalg.norm(embedding)
                if norm > 0:
                    embedding = embedding / norm
            
            # Add to index
            self.index.add(embedding.reshape(1, -1))
            
            internal_id = self.next_id
            self.next_id += 1
            
            # Store metadata
            self.id_to_person[internal_id] = person_id
            self.id_to_metadata[internal_id] = {
                'person_id': person_id,
                'source': source,
                'quality': quality_score,
                'hash': face_hash or hashlib.sha256(embedding.tobytes()).hexdigest(),
            }
            
            return internal_id
    
    def search(self, embedding: np.ndarray, k: int = 5, threshold: float = 0.4) -> List[Tuple[int, float]]:
        """
        Search for nearest neighbors.
        
        Args:
            embedding: Query embedding (512-dim)
            k: Number of results to return
            threshold: Minimum similarity score to return (0.0-1.0 for cosine, lower=more similar)
        
        Returns:
            List of (person_id, distance) tuples
        """
        with self.lock:
            if self.index.ntotal == 0:
                return []
            
            embedding = embedding.astype(np.float32)
            
            # Normalize for cosine
            if self.metric == 'cosine':
                norm = np.linalg.norm(embedding)
                if norm > 0:
                    embedding = embedding / norm
            
            # Search FAISS index
            distances, indices = self.index.search(embedding.reshape(1, -1), min(k, self.index.ntotal))
            
            results = []
            for i, idx in enumerate(indices[0]):
                distance = float(distances[0][i])
                
                # Filter by threshold
                if self.metric == 'cosine':
                    # Convert L2 distance to similarity score (0-1)
                    # For normalized vectors: L2_dist = sqrt(2 - 2*cosine_sim)
                    similarity = 1.0 - (distance ** 2) / 2.0
                    if similarity < threshold:
                        continue
                else:
                    if distance > threshold:
                        continue
                
                person_id = self.id_to_person.get(int(idx))
                if person_id is not None:
                    results.append((person_id, similarity if self.metric == 'cosine' else distance))
            
            return results[:k]
    
    def search_unknown(self, embedding: np.ndarray, k: int = 5, 
                       threshold: float = 0.5) -> List[Tuple[int, float, dict]]:
        """
        Search among unknown candidates.
        
        Args:
            embedding: Query embedding
            k: Number of results
            threshold: Minimum similarity
        
        Returns:
            List of (internal_id, similarity, metadata) tuples
        """
        with self.lock:
            if self.index.ntotal == 0:
                return []
            
            embedding = embedding.astype(np.float32)
            
            if self.metric == 'cosine':
                norm = np.linalg.norm(embedding)
                if norm > 0:
                    embedding = embedding / norm
            
            distances, indices = self.index.search(embedding.reshape(1, -1), min(k, self.index.ntotal))
            
            results = []
            for i, idx in enumerate(indices[0]):
                distance = float(distances[0][i])
                idx = int(idx)
                
                if self.metric == 'cosine':
                    similarity = 1.0 - (distance ** 2) / 2.0
                    if similarity < threshold:
                        continue
                else:
                    if distance > threshold:
                        continue
                
                metadata = self.id_to_metadata.get(idx, {})
                results.append((idx, similarity if self.metric == 'cosine' else distance, metadata))
            
            return results[:k]
    
    def batch_search(self, embeddings: np.ndarray, k: int = 5, threshold: float = 0.4) -> List[List[Tuple[int, float]]]:
        """
        Search multiple embeddings.
        
        Args:
            embeddings: Array of shape (n, 512)
            k: Results per query
            threshold: Similarity threshold
        
        Returns:
            List of results per query
        """
        with self.lock:
            embeddings = embeddings.astype(np.float32)
            
            if self.metric == 'cosine':
                norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
                embeddings = embeddings / (norms + 1e-6)
            
            distances, indices = self.index.search(embeddings, min(k, self.index.ntotal))
            
            all_results = []
            for query_idx in range(embeddings.shape[0]):
                results = []
                for i, idx in enumerate(indices[query_idx]):
                    distance = float(distances[query_idx][i])
                    
                    if self.metric == 'cosine':
                        similarity = 1.0 - (distance ** 2) / 2.0
                        if similarity < threshold:
                            continue
                    else:
                        if distance > threshold:
                            continue
                    
                    person_id = self.id_to_person.get(int(idx))
                    if person_id is not None:
                        results.append((person_id, similarity if self.metric == 'cosine' else distance))
                
                all_results.append(results[:k])
            
            return all_results
    
    def get_all_for_person(self, person_id: int) -> List[Tuple[int, dict]]:
        """
        Get all embeddings for a person.
        
        Args:
            person_id: Person ID
        
        Returns:
            List of (internal_id, metadata) tuples
        """
        with self.lock:
            results = []
            for internal_id, pid in self.id_to_person.items():
                if pid == person_id:
                    metadata = self.id_to_metadata.get(internal_id, {})
                    results.append((internal_id, metadata))
            return results
    
    def remove(self, internal_id: int) -> bool:
        """Remove embedding by internal ID (rebuild index)."""
        with self.lock:
            if internal_id not in self.id_to_person:
                return False
            
            # FAISS doesn't support removal, so rebuild index
            del self.id_to_person[internal_id]
            del self.id_to_metadata[internal_id]
            
            # Rebuild index
            self._rebuild_index()
            return True
    
    def _rebuild_index(self):
        """Rebuild index from remaining embeddings."""
        # This is a placeholder - in production, use FAISS's IndexIDMap
        # or maintain a separate persistent storage
        logger.debug("[FAISS] Index rebuild needed (not optimized)")
    
    def clear(self):
        """Clear all embeddings."""
        with self.lock:
            self.id_to_person.clear()
            self.id_to_metadata.clear()
            self.next_id = 0
            
            # Reinitialize index
            if self.index_type == 'flat':
                if self.metric == 'cosine':
                    self.index = self.faiss.IndexFlatL2(self.embedding_dim)
                else:
                    self.index = self.faiss.IndexFlatL2(self.embedding_dim)
    
    def save(self, index_path: str, metadata_path: str):
        """Save index and metadata to disk."""
        with self.lock:
            self.faiss.write_index(self.index, index_path)
            
            metadata = {
                'id_to_person': self.id_to_person,
                'id_to_metadata': self.id_to_metadata,
                'next_id': self.next_id,
                'embedding_dim': self.embedding_dim,
                'index_type': self.index_type,
                'metric': self.metric,
            }
            with open(metadata_path, 'wb') as f:
                pickle.dump(metadata, f)
            
            logger.info(f"[FAISS] Saved index to {index_path}")
    
    def load(self, index_path: str, metadata_path: str):
        """Load index and metadata from disk."""
        with self.lock:
            if os.path.exists(index_path) and os.path.exists(metadata_path):
                self.index = self.faiss.read_index(index_path)
                
                with open(metadata_path, 'rb') as f:
                    metadata = pickle.load(f)
                
                self.id_to_person = metadata['id_to_person']
                self.id_to_metadata = metadata['id_to_metadata']
                self.next_id = metadata['next_id']
                
                logger.info(f"[FAISS] Loaded {self.index.ntotal} embeddings from {index_path}")
                return True
            
            return False
    
    def get_stats(self) -> dict:
        """Get index statistics."""
        with self.lock:
            return {
                'total_embeddings': self.index.ntotal if self.index else 0,
                'unique_persons': len(set(self.id_to_person.values())),
                'index_type': self.index_type,
                'metric': self.metric,
            }
