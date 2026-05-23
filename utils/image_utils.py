# ============================================================
# IMAGE UTILITIES - Optimized for real-time processing
# ============================================================

import cv2
import numpy as np
import base64
from typing import Tuple, Optional


def crop_face_to_b64(frame: np.ndarray, bbox: Tuple[float, float, float, float], 
                     margin: float = 0.2, target_size: Tuple[int, int] = (150, 150),
                     quality: int = 60) -> Optional[str]:
    """
    Crop face from frame and encode as base64 JPEG.
    
    Optimized for fast JPEG encoding with minimal payload.
    
    Args:
        frame: Input frame
        bbox: [x1, y1, x2, y2] bounding box
        margin: Margin around face (ratio of face size)
        target_size: Resize target for smaller payload
        quality: JPEG quality (1-95, lower = smaller but lossy)
    
    Returns:
        Data URL string or None if crop failed
    """
    x1, y1, x2, y2 = [int(v) for v in bbox]
    img_h, img_w = frame.shape[:2]
    
    w = x2 - x1
    h = y2 - y1
    mw = int(w * margin)
    mh = int(h * margin)
    
    x1_crop = max(0, x1 - mw)
    y1_crop = max(0, y1 - mh)
    x2_crop = min(img_w, x2 + mw)
    y2_crop = min(img_h, y2 + mh)
    
    face_crop = frame[y1_crop:y2_crop, x1_crop:x2_crop]
    if face_crop.size == 0:
        return None
    
    # Fast resize
    face_resized = cv2.resize(face_crop, target_size, interpolation=cv2.INTER_LINEAR)
    
    # Fast JPEG encode
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    _, buffer = cv2.imencode('.jpg', face_resized, encode_params)
    
    b64 = base64.b64encode(buffer).decode('utf-8')
    return f"data:image/jpeg;base64,{b64}"


def get_brightness(frame: np.ndarray) -> float:
    """
    Calculate average brightness of frame (0-255).
    Useful for rejecting very dark or over-exposed faces.
    """
    if len(frame.shape) == 3:
        # Convert BGR to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame
    return float(np.mean(gray))


def get_blur_score(frame: np.ndarray) -> float:
    """
    Calculate blur score using Laplacian variance.
    Higher score = sharper image, lower = blurrier.
    
    Typical thresholds:
    - < 50: Very blurry (reject)
    - 50-100: Somewhat blurry (marginal)
    - > 100: Sharp (accept)
    """
    if len(frame.shape) == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame
    
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    return float(laplacian_var)


def estimate_face_pose(landmarks: np.ndarray) -> Tuple[float, float, float]:
    """
    Estimate yaw, pitch, roll from face landmarks.
    
    Uses 2D landmarks projected to estimate head pose.
    Returns angles in degrees.
    
    Args:
        landmarks: Face landmarks [N, 2] array
    
    Returns:
        (yaw, pitch, roll) in degrees
    """
    if landmarks is None or len(landmarks) < 5:
        return 0.0, 0.0, 0.0
    
    # Use 5 landmarks: eyes, nose, corners of mouth
    # Simplified 2D pose estimation
    left_eye = landmarks[0]
    right_eye = landmarks[1]
    nose = landmarks[2]
    left_mouth = landmarks[3]
    right_mouth = landmarks[4]
    
    # Yaw: eye spacing and nose position
    eyes_dist = np.linalg.norm(right_eye - left_eye)
    nose_offset = nose[0] - (left_eye[0] + right_eye[0]) / 2
    yaw = np.arctan2(nose_offset, eyes_dist) * 180 / np.pi
    
    # Pitch: nose vertical position relative to eyes
    eye_level = (left_eye[1] + right_eye[1]) / 2
    pitch = np.arctan2(nose[1] - eye_level, eyes_dist) * 180 / np.pi
    
    # Roll: eye level
    roll = np.arctan2(right_eye[1] - left_eye[1], 
                      right_eye[0] - left_eye[0]) * 180 / np.pi
    
    return float(yaw), float(pitch), float(roll)


def calculate_face_area(bbox: Tuple[float, float, float, float]) -> float:
    """Calculate face bounding box area."""
    x1, y1, x2, y2 = bbox
    return float((x2 - x1) * (y2 - y1))


def bbox_iou(box1: np.ndarray, box2: np.ndarray) -> float:
    """
    Calculate Intersection over Union (IoU) between two boxes.
    Used for tracking association.
    """
    x1_min, y1_min, x1_max, y1_max = box1
    x2_min, y2_min, x2_max, y2_max = box2
    
    # Calculate intersection
    inter_xmin = max(x1_min, x2_min)
    inter_ymin = max(y1_min, y2_min)
    inter_xmax = min(x1_max, x2_max)
    inter_ymax = min(y1_max, y2_max)
    
    if inter_xmax < inter_xmin or inter_ymax < inter_ymin:
        return 0.0
    
    inter_area = (inter_xmax - inter_xmin) * (inter_ymax - inter_ymin)
    
    # Calculate union
    box1_area = (x1_max - x1_min) * (y1_max - y1_min)
    box2_area = (x2_max - x2_min) * (y2_max - y2_min)
    union_area = box1_area + box2_area - inter_area
    
    return float(inter_area / union_area) if union_area > 0 else 0.0


def draw_tracked_face(frame: np.ndarray, bbox: Tuple[float, float, float, float],
                      track_id: int, name: Optional[str] = None, 
                      similarity: Optional[float] = None,
                      liveness_score: Optional[float] = None,
                      quality_score: Optional[float] = None,
                      is_target: bool = False,
                      color: Tuple[int, int, int] = (0, 255, 255)):
    """
    Draw professional debug overlay for tracked face.
    
    Args:
        frame: Input frame
        bbox: [x1, y1, x2, y2] bounding box
        track_id: Track ID number
        name: Recognized name (optional)
        similarity: Similarity score (optional)
        liveness_score: Liveness confidence (optional)
        quality_score: Quality score (optional)
        is_target: Whether this is the target face
        color: Box color (BGR)
    """
    import math
    import time
    
    x1, y1, x2, y2 = [int(v) for v in bbox]
    thickness = 3 if is_target else 1
    
    # Main bounding box
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
    
    # Track ID label
    track_label = f"ID:{track_id}"
    cv2.putText(frame, track_label, (x1, y1 - 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    
    # Recognition label
    if name:
        cv2.putText(frame, f">> {name} <<", (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    
    # Info line below box
    info_lines = []
    if similarity is not None:
        info_lines.append(f"Sim:{similarity:.3f}")
    if liveness_score is not None:
        info_lines.append(f"Live:{liveness_score:.2f}")
    if quality_score is not None:
        info_lines.append(f"Q:{quality_score:.2f}")
    
    if info_lines:
        info_text = " | ".join(info_lines)
        cv2.putText(frame, info_text, (x1, y2 + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    
    # Draw center circle for target
    if is_target:
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        pulse = (math.sin(time.time() * 3) + 1) / 2
        cv2.circle(frame, (cx, cy), 4, (0, 0, 255), -1)
        cv2.circle(frame, (cx, cy), int(10 + 5 * pulse), (0, 0, 255), 1)
