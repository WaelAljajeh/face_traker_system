#!/usr/bin/env python3
"""
Minimal Live Camera Recognition Test
=====================================
Strips away tracking, quality filters, liveness, and temporal aggregation.
Shows raw recognition results frame-by-frame.

Usage:
    python live_minimal_test.py
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
print("MINIMAL LIVE RECOGNITION TEST")
print("=" * 60)

config = Config.load("config.yaml")
recognition_cfg = config.get_section("recognition")
threshold = recognition_cfg.get("similarity_threshold", 0.45)

detector = FaceDetector(
    model_name=config.get_section("insightface").get("model_name", "buffalo_l"),
    confidence_threshold=0.60  # More lenient for testing
)

recognizer = FaceRecognizer(
    recognition_cfg.get("db_path", "registered_faces"),
    detector=detector,
    normalize=True
)

camera_cfg = config.get_section("camera")
device_id = camera_cfg.get("source", 0)

cap = cv2.VideoCapture(device_id)
if not cap.isOpened():
    print(f"❌ Cannot open camera {device_id}")
    sys.exit(1)

print(f"\n📷 Camera open (device={device_id})")
print(f"🎯 Threshold: {threshold}")
print(f"👥 Database: {list(recognizer.database_embeddings.keys())}")
print("\nLook at the camera. Press 'q' to quit.\n")

frame_count = 0
last_status = ""

while True:
    ret, frame = cap.read()
    if not ret:
        continue

    frame_count += 1
    display = frame.copy()

    # Raw detection
    detections, _ = detector.detect(frame)

    if not detections:
        status = "NO FACE"
        cv2.putText(display, status, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
    else:
        for det in detections:
            bbox = det['bbox']
            emb = det['embedding']
            conf = det.get('confidence', 0)

            x1, y1, x2, y2 = map(int, bbox)

            # RAW recognition - no filters, no tracking, no temporal agg
            name, distance, all_scores = recognizer.identify(emb, threshold=threshold)

            if name:
                color = (0, 255, 0)
                label = f"{name} | dist={distance:.3f}"
                status = f"✅ MATCH: {name} @ {distance:.3f}"
            else:
                color = (0, 165, 255)
                if all_scores:
                    best_name = min(all_scores, key=all_scores.get)
                    best_dist = all_scores[best_name]
                    label = f"? {best_name} @ {best_dist:.3f}"
                    status = f"❌ NO MATCH | best={best_name} @ {best_dist:.3f} (thr={threshold})"
                else:
                    label = "?"
                    status = "❌ NO MATCH | no scores"

            cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)
            cv2.putText(display, label, (x1, y1 - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

            # Print only when status changes
            if status != last_status:
                print(f"[Frame {frame_count}] {status} | detect_conf={conf:.2f}")
                last_status = status

    cv2.putText(display, "Press 'q' to quit", (20, frame.shape[0] - 20),
               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    cv2.imshow("Minimal Live Test", display)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
print("\nDone.")
