#!/usr/bin/env python3
"""
Optimized Live Camera Recognition for Client Laptops
=======================================================
- Lower resolution
- Frame skipping
- Smaller detection input
- FPS counter

Usage:
    python live_optimized.py
"""

import sys
import os
import cv2
import numpy as np
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import Config
from core import FaceDetector, FaceRecognizer

print("=" * 60)
print("OPTIMIZED LIVE RECOGNITION - CLIENT LAPTOP MODE")
print("=" * 60)

config = Config.load("config.yaml")
recognition_cfg = config.get_section("recognition")
threshold = recognition_cfg.get("similarity_threshold", 0.45)

# PERFORMANCE SETTINGS FOR CLIENT LAPTOPS
perf_cfg = config.get_section("performance") or {}
inference_every_n = perf_cfg.get("inference_every_n_frames", 3)  # Skip frames
frame_scale = perf_cfg.get("frame_scale", 0.5)                   # Downscale

# Use smaller model if configured, else default
insight_cfg = config.get_section("insightface") or {}
model_name = insight_cfg.get("model_name", "buffalo_s")  # buffalo_s = lighter

detector = FaceDetector(
    model_name=model_name,
    confidence_threshold=0.60
)

recognizer = FaceRecognizer(
    recognition_cfg.get("db_path", "registered_faces"),
    detector=detector,
    normalize=True
)

camera_cfg = config.get_section("camera")
device_id = camera_cfg.get("source", 0)

# Open camera at lower resolution for speed
cap = cv2.VideoCapture(device_id)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, camera_cfg.get("width", 640))
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, camera_cfg.get("height", 480))
cap.set(cv2.CAP_PROP_FPS, camera_cfg.get("fps", 15))

if not cap.isOpened():
    print(f"Cannot open camera {device_id}")
    sys.exit(1)

print(f"Camera: {device_id} | Model: {model_name} | Threshold: {threshold}")
print(f"Skip frames: {inference_every_n} | Scale: {frame_scale}")
print(f"DB: {list(recognizer.database_embeddings.keys())}")
print("\nLook at camera. Press 'q' to quit.\n")

frame_count = 0
last_status = ""
last_detections = []  # Cache detections between frames
last_display_time = time.time()
fps_display = 0

while True:
    ret, frame = cap.read()
    if not ret:
        continue

    frame_count += 1
    display = frame.copy()
    h, w = frame.shape[:2]

    # Only run heavy detection every Nth frame
    if frame_count % inference_every_n == 0:
        # Downscale for faster detection
        if frame_scale < 1.0:
            small_frame = cv2.resize(frame, (int(w * frame_scale), int(h * frame_scale)))
            detections, _ = detector.detect(small_frame)
            # Scale bboxes back to original resolution
            for det in detections:
                bbox = det["bbox"]
                det["bbox"] = [
                    bbox[0] / frame_scale,
                    bbox[1] / frame_scale,
                    bbox[2] / frame_scale,
                    bbox[3] / frame_scale,
                ]
        else:
            detections, _ = detector.detect(frame)
        last_detections = detections
    else:
        detections = last_detections  # Reuse last known positions

    if not detections:
        status = "NO FACE"
        cv2.putText(display, status, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
    else:
        for det in detections:
            bbox = det["bbox"]
            emb = det["embedding"]
            conf = det.get("confidence", 0)
            x1, y1, x2, y2 = map(int, bbox)

            name, distance, all_scores = recognizer.identify(emb, threshold=threshold)

            if name:
                color = (0, 255, 0)
                label = f"{name} | {distance:.3f}"
                status = f"MATCH: {name} @ {distance:.3f}"
            else:
                color = (0, 165, 255)
                if all_scores:
                    best_name = min(all_scores, key=all_scores.get)
                    best_dist = all_scores[best_name]
                    label = f"? {best_name} @ {best_dist:.3f}"
                    status = f"NO MATCH | best={best_name} @ {best_dist:.3f}"
                else:
                    label = "?"
                    status = "NO MATCH | no scores"

            cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)
            cv2.putText(display, label, (x1, y1 - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

            if status != last_status:
                print(f"[Frame {frame_count}] {status} | detect_conf={conf:.2f}")
                last_status = status

    # FPS counter
    now = time.time()
    fps_display = 1.0 / (now - last_display_time) if (now - last_display_time) > 0 else 0
    last_display_time = now
    cv2.putText(display, f"FPS: {fps_display:.1f} | Frame: {frame_count}",
                (20, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

    cv2.imshow("Optimized Live Test", display)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
print("\nDone.")
