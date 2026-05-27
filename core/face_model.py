# core/face_model.py
"""
Shared InsightFace singleton – ensures same model, same preprocessing,
same embedding extraction for both detector and embedder.
"""

import insightface
import numpy as np
from typing import List, Tuple, Optional

_global_face_app = None
_global_config = None


def get_face_app(
    model_name: str = 'buffalo_l',
    det_size: Tuple[int, int] = (640, 640),
    det_thresh: float = 0.5,
    providers: List[str] = None,
) -> insightface.app.FaceAnalysis:
    """
    Singleton FaceAnalysis instance.
    All calls with the same model_name return the same instance.
    """
    global _global_face_app, _global_config
    
    if providers is None:
        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
    
    current_config = (model_name, det_size, det_thresh, tuple(providers))
    
    if _global_face_app is None or _global_config != current_config:
        print(f"[SHARED] Initializing InsightFace: model={model_name}, det_size={det_size}, thresh={det_thresh}")
        _global_face_app = insightface.app.FaceAnalysis(name=model_name, providers=providers)
        _global_face_app.prepare(ctx_id=0, det_thresh=det_thresh, det_size=det_size)
        _global_config = current_config
        print("[SHARED] ✅ InsightFace ready (singleton)")
    
    return _global_face_app


def normalize_embedding(embedding: np.ndarray) -> np.ndarray:
    """L2-normalize embedding to unit length."""
    if embedding is None:
        return None
    norm = np.linalg.norm(embedding)
    if norm > 0:
        return embedding / norm
    return embedding