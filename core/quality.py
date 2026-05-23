# ============================================================
# QUALITY FILTERING MODULE
# ============================================================
# Filters faces based on:
# - Blur (Laplacian variance)
# - Pose (yaw, pitch, roll)
# - Brightness
# - Face size
# - Landmarks visibility

from typing import Tuple
import numpy as np
import cv2
from utils.image_utils import get_blur_score, get_brightness, estimate_face_pose


class QualityFilter:
    """
    Face quality assessment and filtering.
    
    Rejects:
    - Blurry faces
    - Extreme head poses
    - Too dark/bright faces
    - Very small faces
    """
    
    def __init__(self, config: dict):
        """
        Initialize quality filter.
        
        Args:
            config: Config section from YAML:
                - blur_detection: bool
                - blur_threshold: float
                - pose_filtering: bool
                - max_yaw/pitch/roll: float
                - brightness_filtering: bool
                - min/max_brightness: float
                - min_face_size: int
                - occlusion_filtering: bool
                - max_occlusion_ratio: float
        """
        self.blur_detection = config.get('blur_detection', True)
        self.blur_threshold = config.get('blur_threshold', 100.0)
        
        self.pose_filtering = config.get('pose_filtering', True)
        self.max_yaw = config.get('max_yaw', 45)
        self.max_pitch = config.get('max_pitch', 35)
        self.max_roll = config.get('max_roll', 30)
        
        self.brightness_filtering = config.get('brightness_filtering', True)
        self.min_brightness = config.get('min_brightness', 40)
        self.max_brightness = config.get('max_brightness', 220)
        
        self.min_face_size = config.get('min_face_size', 60)
        self.occlusion_filtering = config.get('occlusion_filtering', True)
        self.max_occlusion_ratio = config.get('max_occlusion_ratio', 0.3)
    
    def assess(self, frame: np.ndarray, detection: dict, 
               crop_margin: float = 0.2) -> Tuple[bool, float, dict]:
        """
        Assess face quality and return pass/fail.
        
        Args:
            frame: Full frame
            detection: Detection dict with bbox, landmarks
            crop_margin: Margin for face crop
        
        Returns:
            (pass: bool, quality_score: float (0-1), reasons: dict)
        """
        quality_score = 1.0
        reasons = {}
        
        bbox = detection['bbox']
        landmarks = detection.get('landmarks')
        
        x1, y1, x2, y2 = [int(v) for v in bbox]
        
        # 1. Check face size
        w = x2 - x1
        h = y2 - y1
        if w < self.min_face_size or h < self.min_face_size:
            reasons['face_too_small'] = f"({w}x{h})"
            quality_score *= 0.0
        
        # 2. Check blur
        if self.blur_detection:
            face_crop = frame[y1:y2, x1:x2]
            blur_score = get_blur_score(face_crop)
            if blur_score < self.blur_threshold:
                reasons['blur'] = f"{blur_score:.1f} < {self.blur_threshold}"
                quality_score *= 0.3
        
        # 3. Check brightness
        if self.brightness_filtering:
            face_crop = frame[y1:y2, x1:x2]
            brightness = get_brightness(face_crop)
            if brightness < self.min_brightness or brightness > self.max_brightness:
                reasons['brightness'] = f"{brightness:.1f}"
                quality_score *= 0.4
        
        # 4. Check pose
        if self.pose_filtering and landmarks is not None:
            yaw, pitch, roll = estimate_face_pose(landmarks)
            pose_penalty = 1.0
            
            if abs(yaw) > self.max_yaw:
                reasons['yaw'] = f"{yaw:.1f}°"
                pose_penalty *= 0.5
            if abs(pitch) > self.max_pitch:
                reasons['pitch'] = f"{pitch:.1f}°"
                pose_penalty *= 0.5
            if abs(roll) > self.max_roll:
                reasons['roll'] = f"{roll:.1f}°"
                pose_penalty *= 0.5
            
            quality_score *= pose_penalty
        
        # 5. Check occlusion (landmarks visibility)
        if self.occlusion_filtering and landmarks is not None:
            # Simple check: if landmarks spread is within bbox
            lm_min_x = np.min(landmarks[:, 0])
            lm_max_x = np.max(landmarks[:, 0])
            lm_min_y = np.min(landmarks[:, 1])
            lm_max_y = np.max(landmarks[:, 1])
            
            lm_width = lm_max_x - lm_min_x
            lm_height = lm_max_y - lm_min_y
            bbox_width = w
            bbox_height = h
            
            occlusion_ratio = 1.0 - ((lm_width / bbox_width) * (lm_height / bbox_height))
            if occlusion_ratio > self.max_occlusion_ratio:
                reasons['occlusion'] = f"{occlusion_ratio:.2f}"
                quality_score *= 0.5
        
        # Final decision
        passed = quality_score > 0.5
        
        if reasons:
            reason_str = ", ".join([f"{k}={v}" for k, v in reasons.items()])
            print(f"[QUALITY] ❌ {reason_str} (score: {quality_score:.2f})")
        else:
            print(f"[QUALITY] ✅ Pass (score: {quality_score:.2f})")
        
        return passed, quality_score, reasons
