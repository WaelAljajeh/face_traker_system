# ============================================================
# DETECTOR MODULE - Face Detection with InsightFace
# ============================================================
# Wraps InsightFace SCRFD detector with:
# - Initialization with configurable providers
# - Batch detection support
# - Performance profiling
# - Confidence filtering

from typing import List, Tuple, Optional
import numpy as np
from insightface.app import FaceAnalysis
from utils.metrics import get_metrics


class FaceDetector:
    """
    Face detector using InsightFace (SCRFD + ArcFace).
    
    Keeps models in memory for fast inference.
    """
    
    def __init__(self, model_name: str = 'buffalo_l',
                 providers: List[str] = None,
                 det_size: Tuple[int, int] = (320, 320),
                 confidence_threshold: float = 0.70):
        """
        Initialize detector with production settings.
        
        Args:
            model_name: InsightFace model ('buffalo_l' recommended for production)
            providers: ONNX Runtime providers (GPU first, fallback to CPU)
            det_size: Detection input size
            confidence_threshold: Min detection confidence (0.70-0.75 recommended for production)
        """
        if providers is None:
            providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        
        self.confidence_threshold = confidence_threshold
        self.metrics = get_metrics()
        self.app = None
        
        # Initialize InsightFace
        print(f"[DETECTOR] Initializing InsightFace ({model_name})...")
        try:
            self.app = FaceAnalysis(name=model_name, providers=providers)
            self.app.prepare(ctx_id=0, det_size=det_size)
            print(f"[DETECTOR] ✅ Ready (providers: {providers})")
        except Exception as e:
            print(f"[ERROR] Failed to initialize detector: {e}")
            print("[INFO] Ensure InsightFace is installed: pip install insightface>=0.7.3")
            raise
    
    def detect(self, frame: np.ndarray) -> Tuple[List[dict], float]:
        """
        Detect faces in frame.
        
        Args:
            frame: Input frame (BGR)
        
        Returns:
            List of detections with keys:
            - bbox: [x1, y1, x2, y2]
            - confidence: Detection confidence
            - kps: Landmarks (5 points)
            - embedding: Face embedding (512-dim ArcFace)
            
            Elapsed time (ms)
        """
        self.metrics.start_timer("detect")
        
        faces = self.app.get(frame)
        
        detections = []
        for face in faces:
            if face.det_score < self.confidence_threshold:
                continue
            
            det = {
                'bbox': face.bbox.astype(np.float32),
                'confidence': float(face.det_score),
                'landmarks': face.kps.astype(np.float32) if hasattr(face, 'kps') else None,
                'embedding': face.embedding.astype(np.float32),
            }
            detections.append(det)
        
        elapsed = self.metrics.end_timer("detect")
        return detections, elapsed
    
    def extract_embedding(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        Extract embedding from frame with single largest face.
        
        Args:
            frame: Input frame
        
        Returns:
            Face embedding (512-dim normalized) or None if no face
        """
        faces = self.app.get(frame)
        if not faces:
            return None
        return faces[0].embedding.astype(np.float32)
