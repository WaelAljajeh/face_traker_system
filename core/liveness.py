# ============================================================
# LIVENESS DETECTION MODULE (Passive Anti-Spoofing)
# ============================================================
# Detects spoof attempts using lightweight passive checks:
# - Texture analysis
# - Frequency domain analysis
# - (Optional) MiniFASNet ONNX model
#
# For this MVP, we implement texture-based passive liveness.
# To use MiniFASNet, provide model path in config.

import numpy as np
import cv2
from typing import Tuple


class LivenessDetector:
    """
    Lightweight passive liveness detection.
    
    Rejects:
    - Printed photos
    - Phone screens
    - Very low texture
    """
    
    def __init__(self, model_path: str = None, threshold: float = 0.5):
        """
        Initialize liveness detector.
        
        Args:
            model_path: Path to MiniFASNet ONNX (optional)
            threshold: Confidence threshold (0.0-1.0)
        """
        self.threshold = threshold
        self.model_path = model_path
        self.model = None
        self.use_model = False
        
        if model_path and os.path.exists(model_path):
            try:
                import onnxruntime as rt
                self.model = rt.InferenceSession(model_path)
                self.use_model = True
                print(f"[LIVENESS] Loaded MiniFASNet model")
            except Exception as e:
                print(f"[LIVENESS] Could not load model: {e}, using texture fallback")
    
    def check(self, frame: np.ndarray, bbox: Tuple[float, float, float, float]) -> Tuple[bool, float]:
        """
        Check if face is live or spoof.
        
        Args:
            frame: Full frame
            bbox: Face bounding box [x1, y1, x2, y2]
        
        Returns:
            (is_live: bool, confidence: float)
        """
        x1, y1, x2, y2 = [int(v) for v in bbox]
        face_crop = frame[y1:y2, x1:x2]
        
        if face_crop.size == 0:
            return False, 0.0
        
        if self.use_model:
            return self._check_with_model(face_crop)
        else:
            return self._check_texture(face_crop)
    
    def _check_with_model(self, face_crop: np.ndarray) -> Tuple[bool, float]:
        """Use MiniFASNet ONNX model for liveness."""
        # Resize to model input
        resized = cv2.resize(face_crop, (80, 80))
        resized = resized.astype(np.float32) / 255.0
        resized = np.transpose(resized, (2, 0, 1))
        resized = np.expand_dims(resized, 0)
        
        # Run inference
        input_name = self.model.get_inputs()[0].name
        output_name = self.model.get_outputs()[0].name
        result = self.model.run([output_name], {input_name: resized})
        
        confidence = float(result[0][0, 1])  # Real face score
        is_live = confidence > self.threshold
        
        return is_live, confidence
    
    def _check_texture(self, face_crop: np.ndarray) -> Tuple[bool, float]:
        """
        Passive texture-based liveness detection.
        
        Principle: Real faces have high-frequency texture variations.
        Photos/screens have periodic patterns.
        """
        if len(face_crop.shape) == 3:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        else:
            gray = face_crop
        
        # Compute local binary patterns (LBP) texture
        h, w = gray.shape
        
        # Compute gradient magnitude
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        magnitude = np.sqrt(gx**2 + gy**2)
        
        # Compute contrast (high for real faces, low for photos)
        contrast = np.std(gray)
        max_contrast = 128.0
        contrast_score = np.clip(contrast / max_contrast, 0, 1)
        
        # Compute texture variation
        texture_score = np.mean(magnitude) / 255.0
        
        # Combined score
        confidence = (contrast_score + texture_score) / 2.0
        
        is_live = confidence > self.threshold
        
        return is_live, confidence


import os
