import numpy as np
import cv2
import logging

logger = logging.getLogger(__name__)


class FaceEmbedder:
    """
    Face embedding extractor using InsightFace (ArcFace model).
    Extracts 512-dimensional normalized embeddings from face images.
    """
    
    def __init__(self, model=None):
        """
        Initialize embedder with InsightFace model.
        
        Args:
            model: Optional pre-loaded model. If None, loads InsightFace automatically.
        """
        self.model = model
        self.app = None
        
        if self.model is None:
            try:
                import insightface
                # Load InsightFace app with ArcFace model
                self.app = insightface.app.FaceAnalysis(
                    providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
                )
                self.app.prepare(ctx_id=0, det_thresh=0.5, det_size=(640, 640))
                logger.info("[EMBEDDER] InsightFace loaded successfully")
            except Exception as e:
                logger.error(f"[EMBEDDER] Failed to load InsightFace: {e}")
                raise RuntimeError("InsightFace not available. Install: pip install insightface")

    def extract_embedding(self, frame):
        """
        Extract 512-dim embedding from face image.
        
        Args:
            frame: BGR image (OpenCV format) or path to image file
            
        Returns:
            np.ndarray: 512-dimensional normalized embedding, or None if no face detected
        """
        if frame is None:
            return None
        
        try:
            # Handle file path input
            if isinstance(frame, str):
                frame = cv2.imread(frame)
                if frame is None:
                    logger.warning(f"[EMBEDDER] Could not read image: {frame}")
                    return None
            
            # Ensure frame is in BGR format
            if len(frame.shape) == 2:  # Grayscale
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            
            # Detect faces and extract embeddings
            faces = self.app.get(frame)
            
            if not faces or len(faces) == 0:
                logger.debug("[EMBEDDER] No face detected in image")
                return None
            
            # Get the first (largest) face embedding
            face = faces[0]
            embedding = face.embedding
            
            # Ensure it's float32 and normalized
            embedding = np.array(embedding, dtype=np.float32)
            
            # Normalize to unit length (L2 normalization)
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
            
            logger.debug(f"[EMBEDDER] Extracted embedding for face (confidence: {face.det_score:.3f})")
            return embedding
            
        except Exception as e:
            logger.error(f"[EMBEDDER] Error extracting embedding: {e}")
            return None
    
    def extract_embeddings_batch(self, frames):
        """
        Extract embeddings from multiple frames at once.
        
        Args:
            frames: List of BGR images
            
        Returns:
            List[np.ndarray]: List of embeddings (same length as frames, None for failed extractions)
        """
        embeddings = []
        for frame in frames:
            embedding = self.extract_embedding(frame)
            embeddings.append(embedding)
        return embeddings
    
    def preprocess(self, frame):
        """
        Preprocess frame for embedding extraction (optional normalization).
        
        Args:
            frame: Input image
            
        Returns:
            Preprocessed image
        """
        # InsightFace handles preprocessing internally
        return frame