#!/usr/bin/env python3
"""
Live Camera + Flask Server Client (with Unknown Face Handling)
================================================================
- Sends KNOWN faces: member_id only (attendance record)
- Sends UNKNOWN faces: image_base64 (for admin review/enrollment)
- Server stores both in pending_scans table

Usage:
    python live_server_client.py
"""

import sys
import os
import cv2
import numpy as np
import time
import threading
import queue
import requests
import base64

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import Config
from core import FaceDetector, FaceRecognizer
from models.database import init_database
from services.database_service import DatabaseService
from services.vector_database import FAISSVectorDB

print("=" * 60)
print("LIVE CAMERA + SERVER CLIENT")
print("=" * 60)

config = Config.load("config.yaml")
recognition_cfg = config.get_section("recognition")
threshold = recognition_cfg.get("similarity_threshold", 0.45)

perf_cfg = config.get_section("performance") or {}
inference_every_n = perf_cfg.get("inference_every_n_frames", 2)
frame_scale = perf_cfg.get("frame_scale", 0.5)

insight_cfg = config.get_section("insightface") or {}
model_name = insight_cfg.get("model_name", "buffalo_s")

# ── SERVER CONFIG ──
server_cfg = config.get_section("server") or {}
SERVER_URL = server_cfg.get("url", "http://localhost:8000")
SERVER_TIMEOUT = server_cfg.get("timeout", 10)

# ── INITIALIZE DATABASE ──
engine, SessionLocal = init_database("face_attendance.db")
db_service = DatabaseService(SessionLocal)
vector_db = FAISSVectorDB(embedding_dim=512)

# ── INITIALIZE AI MODELS ──
detector = FaceDetector(
    model_name=model_name,
    confidence_threshold=0.60
)

recognizer = FaceRecognizer(
    db_service=db_service,
    vector_db=vector_db,
    normalize=True
)

camera_cfg = config.get_section("camera")
device_id = camera_cfg.get("source", 0)

print(f"Camera: {device_id} | Model: {model_name} | Threshold: {threshold}")
print(f"Server: {SERVER_URL}")
print(f"DB: Loaded {len(recognizer.database)} embeddings")

# ─────────────────────────────────────────────────────────────
# THREADING SETUP
# ─────────────────────────────────────────────────────────────

frame_queue = queue.Queue(maxsize=2)
result_queue = queue.Queue()
latest_results = {}
results_lock = threading.Lock()
frame_counter = 0
counter_lock = threading.Lock()
KILL_SIGNAL = None

# Cooldown timers
last_scan_time = {}
last_unknown_time = 0
SCAN_COOLDOWN_SECONDS = 8      # Between scans of same known person
UNKNOWN_COOLDOWN_SECONDS = 10  # Between unknown face submissions


def send_known(member_id):
    """Send recognized person to server."""
    try:
        resp = requests.post(
            f"{SERVER_URL}/scan",
            json={"member_id": str(member_id)},
            timeout=SERVER_TIMEOUT
        )
        if resp.status_code == 200:
            print(f"  [SERVER] Known scan: {member_id}")
            return True
        else:
            print(f"  [SERVER] Error {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"  [SERVER] Failed: {e}")
    return False


def send_unknown(image_b64):
    """Send unknown face image to server for later review."""
    try:
        resp = requests.post(
            f"{SERVER_URL}/scan",
            json={
                "member_id": None,
                "image_base64": image_b64
            },
            timeout=SERVER_TIMEOUT
        )
        if resp.status_code == 200:
            print(f"  [SERVER] Unknown face submitted for review")
            return True
        else:
            print(f"  [SERVER] Error {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"  [SERVER] Failed: {e}")
    return False


def detection_worker():
    """Background thread: runs AI, posts results."""
    while True:
        item = frame_queue.get()
        if item is KILL_SIGNAL:
            break
        fid, small_frame, scale, full_frame_b64 = item

        try:
            detections, _ = detector.detect(small_frame)
            if scale < 1.0:
                for det in detections:
                    bbox = det["bbox"]
                    det["bbox"] = [
                        float(bbox[0] / scale), float(bbox[1] / scale),
                        float(bbox[2] / scale), float(bbox[3] / scale),
                    ]
            
            for det in detections:
                emb = det["embedding"]
                # Use new recognizer.identify() signature
                result, best_score, all_scores = recognizer.identify(emb, threshold=threshold)
                
                name = result.get("name") if result else None
                confidence = result.get("confidence", 0.0) if result else 0.0
                
                det["name"] = str(name) if name else None
                det["distance"] = float(best_score) if best_score is not None else 0.0
                det["confidence"] = float(confidence)
        except Exception as e:
            print(f"Detection error: {e}")
            detections = []

        try:
            result_queue.put_nowait((fid, detections, full_frame_b64))
        except queue.Full:
            pass
        frame_queue.task_done()


detection_thread = threading.Thread(target=detection_worker, daemon=True)
detection_thread.start()

# ─────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────

cap = cv2.VideoCapture(device_id)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, camera_cfg.get("width", 640))
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, camera_cfg.get("height", 480))
cap.set(cv2.CAP_PROP_FPS, camera_cfg.get("fps", 30))

if not cap.isOpened():
    print(f"Cannot open camera {device_id}")
    sys.exit(1)

print("\nPress 'q' to quit.\n")

frame_count = 0
last_status = ""
last_display_time = time.time()
fps_display = 0

while True:
    ret, frame = cap.read()
    if not ret:
        continue

    frame_count += 1
    h, w = frame.shape[:2]

    # ── SUBMIT TO DETECTION THREAD ──
    if frame_count % inference_every_n == 0:
        with counter_lock:
            current_fid = frame_counter
            frame_counter += 1

        if frame_scale < 1.0:
            small = cv2.resize(frame, (int(w * frame_scale), int(h * frame_scale)))
        else:
            small = frame

        # Encode full frame for unknown face submission
        _, buf = cv2.imencode('.jpg', frame)
        frame_b64 = base64.b64encode(buf).decode('utf-8')

        try:
            frame_queue.put_nowait((current_fid, small, frame_scale, frame_b64))
        except queue.Full:
            try:
                frame_queue.get_nowait()
                frame_queue.task_done()
                frame_queue.put_nowait((current_fid, small, frame_scale, frame_b64))
            except queue.Empty:
                pass

    # ── COLLECT RESULTS ──
    try:
        while True:
            fid, dets, fb64 = result_queue.get_nowait()
            with results_lock:
                latest_results[fid] = (dets, fb64)
            result_queue.task_done()
    except queue.Empty:
        pass

    # ── DRAW ──
    display = frame.copy()

    with results_lock:
        if latest_results:
            best_fid = max(latest_results.keys())
            detections, frame_b64 = latest_results[best_fid]
            for old_fid in list(latest_results.keys()):
                if old_fid < best_fid - 5:
                    del latest_results[old_fid]
        else:
            detections = []
            frame_b64 = None

    if not detections:
        cv2.putText(display, "NO FACE", (20, 40),
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
    else:
        for det in detections:
            bbox = det["bbox"]
            x1, y1, x2, y2 = map(int, bbox)
            name = det.get("name")
            distance = det.get("distance", 0)
            conf = det.get("confidence", 0)

            if name:
                # ── KNOWN FACE ──
                color = (0, 255, 0)
                label = f"{name} | {distance:.3f}"
                status = f"MATCH: {name}"

                now = time.time()
                last_time = last_scan_time.get(name, 0)
                if now - last_time > SCAN_COOLDOWN_SECONDS:
                    last_scan_time[name] = now
                    threading.Thread(
                        target=send_known,
                        args=(name,),
                        daemon=True
                    ).start()
                    label += " [SENT]"
                else:
                    label += " [COOLDOWN]"
            else:
                # ── UNKNOWN FACE ──
                color = (0, 165, 255)
                label = "? UNKNOWN"
                status = "UNKNOWN FACE"

                 
                now = time.time()
                if now - last_unknown_time > UNKNOWN_COOLDOWN_SECONDS:
                    last_unknown_time = now
                    if frame_b64:
                        threading.Thread(
                            target=send_unknown,
                            args=(frame_b64,),
                            daemon=True
                        ).start()
                        label += " [SENT]"
                    else:
                        label += " [NO IMG]"
                else:
                    label += " [COOLDOWN]"

            cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)
            cv2.putText(display, label, (x1, y1 - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            if status != last_status:
                print(f"[Frame {frame_count}] {status} | conf={conf:.2f}")
                last_status = status

    # FPS
    now = time.time()
    fps_display = 1.0 / (now - last_display_time)
    last_display_time = now
    cv2.putText(display, f"FPS: {fps_display:.1f} | Frame: {frame_count}",
                (20, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

    cv2.imshow("Live Camera + Server Client", display)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

# ── SHUTDOWN ──
frame_queue.put(KILL_SIGNAL)
detection_thread.join(timeout=1.0)
cap.release()
cv2.destroyAllWindows()
print("\nDone.")
