# core/detector.py
"""
Face detector using shared InsightFace singleton.
Returns normalized embeddings that match the embedder.
"""

import time
import numpy as np
from typing import List, Tuple, Dict, Optional
from core.face_model import get_face_app, normalize_embedding
from utils.metrics import get_metrics


class FaceDetector:
    """
    Face detector using InsightFace (SCRFD + ArcFace).
    Uses shared singleton to ensure same model as embedder.
    """

    def __init__(
        self,
        model_name: str = 'buffalo_l',
        providers: List[str] = None,
        det_size: Tuple[int, int] = (640, 640),
        det_thresh: float = 0.5,
        confidence_threshold: float = 0.50,
    ):
        """
        Initialize detector – uses shared FaceAnalysis instance.
        """
        self.confidence_threshold = confidence_threshold
        self.det_thresh = det_thresh
        self.det_size = det_size
        self.metrics = get_metrics()

        # Use singleton – identical to embedder
        self.app = get_face_app(
            model_name=model_name,
            det_size=det_size,
            det_thresh=det_thresh,
            providers=providers,
        )

        print(f"[DETECTOR] Using shared InsightFace (det_thresh={det_thresh}, det_size={det_size})")

    def detect(self, frame: np.ndarray) -> Tuple[List[dict], float]:
        """
        Detect faces in frame.

        Returns:
            List of detections with keys:
            - bbox: [x1, y1, x2, y2]
            - confidence: Detection confidence
            - kps: Landmarks (5 points)
            - embedding: Normalized face embedding (unit norm)
            elapsed time (ms)
        """
        self.metrics.start_timer("detect")

        t0 = time.time()
        faces = self.app.get(frame)
        dt = time.time() - t0

        detections = []
        for face in faces:
            score = float(face.det_score)
            if score < self.confidence_threshold:
                continue

            # RAW embedding from InsightFace
            raw_emb = face.embedding.astype(np.float32)
            # Normalize to match stored embeddings
            emb = normalize_embedding(raw_emb)

            det = {
                'bbox': face.bbox.astype(np.float32),
                'confidence': score,
                'landmarks': face.kps.astype(np.float32) if hasattr(face, 'kps') else None,
                'embedding': emb,   # normalized!
            }
            detections.append(det)

        elapsed = self.metrics.end_timer("detect")
        return detections, elapsed

    def extract_embedding(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        Extract normalized embedding of the highest-confidence face.
        """
        faces = self.app.get(frame)
        if not faces:
            return None

        face = max(faces, key=lambda f: f.det_score)
        raw_emb = face.embedding.astype(np.float32)
        return normalize_embedding(raw_emb)