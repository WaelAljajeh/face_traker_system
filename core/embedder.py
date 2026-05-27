# core/embedder.py
"""
Face embedding extractor using shared InsightFace singleton.
Used for enrollment and API calls.
"""

import numpy as np
import cv2
import logging
import time
from core.face_model import get_face_app, normalize_embedding

logger = logging.getLogger(__name__)


class FaceEmbedder:
    """
    Face embedding extractor – uses the same singleton as detector.
    """

    def __init__(
        self,
        model_name: str = 'buffalo_l',
        det_size: tuple = (640, 640),
        det_thresh: float = 0.5,
        providers: list = None,
    ):
        # Use shared singleton – identical to detector!
        self.app = get_face_app(
            model_name=model_name,
            det_size=det_size,
            det_thresh=det_thresh,
            providers=providers,
        )
        print(f"[EMBEDDER] Using shared InsightFace (det_thresh={det_thresh}, det_size={det_size})")

    def extract_embedding(self, frame):
        """
        Extract normalized embedding from the largest face in the frame.
        """
        if frame is None:
            print("[EMBEDDER] ❌ Input frame is None")
            return None

        try:
            if isinstance(frame, str):
                frame = cv2.imread(frame)
                if frame is None:
                    return None

            if len(frame.shape) == 2:
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

            faces = self.app.get(frame)
            if not faces:
                print("[EMBEDDER] ❌ No faces detected")
                return None

            # Pick highest confidence face
            face = max(faces, key=lambda f: getattr(f, 'det_score', 0))
            raw_emb = face.embedding.astype(np.float32)
            emb = normalize_embedding(raw_emb)

            print(f"[EMBEDDER] ✅ Embedding norm: {np.linalg.norm(emb):.4f}")
            return emb

        except Exception as e:
            logger.error(f"[EMBEDDER] Error: {e}")
            return None

    def extract_embeddings_batch(self, frames):
        """Batch extract embeddings."""
        return [self.extract_embedding(f) for f in frames]

    def preprocess(self, frame):
        return frame