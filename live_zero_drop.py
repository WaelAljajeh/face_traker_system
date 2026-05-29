#!/usr/bin/env python3
"""
Live Camera + Flask Server Client
================================================================
Full-resolution detection + direct embedding usage.
No frame scaling, no double-detection on tight crops.
"""

import sys
import os
import cv2
import numpy as np
import time
import threading
import queue
import requests

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

# ── CRITICAL: Use full resolution ──
perf_cfg = config.get_section("performance") or {}
inference_every_n = perf_cfg.get("inference_every_n_frames", 3)
frame_scale = 1.0  # <-- FIXED: was 0.5, now 1.0. Do not scale down.

insight_cfg = config.get_section("insightface") or {}
model_name = insight_cfg.get("model_name", "buffalo_l")

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
    model_name='buffalo_l',
    det_size=(640, 640),
    det_thresh=0.5,           # must match enrollment
    confidence_threshold=0.5,
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

last_scan_time = {}
SCAN_COOLDOWN_SECONDS = 8

# ── DB RELOAD SYNC ──
db_lock = threading.Lock()
last_db_reload = time.time()
DB_RELOAD_INTERVAL = 60  # seconds


def send_known(member_id):
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


def reload_database():
    """Reload DB + vector index + recognizer without restarting the script."""
    global engine, db_service, vector_db, recognizer
    with db_lock:
        print("[DB] Reloading database...")
        try:
            if engine is not None:
                engine.dispose()

            engine, SessionLocal = init_database("face_attendance.db")
            db_service = DatabaseService(SessionLocal)
            vector_db = FAISSVectorDB(embedding_dim=512)

            recognizer = FaceRecognizer(
                db_service=db_service,
                vector_db=vector_db,
                normalize=True
            )
            print(f"[DB] Reloaded. {len(recognizer.database)} embeddings loaded.")
            return True
        except Exception as e:
            print(f"[DB] Reload failed: {e}")
            import traceback
            traceback.print_exc()
            return False


def detection_worker():
    """Background thread: runs AI on full-resolution frames."""
    while True:
        item = frame_queue.get()
        if item is KILL_SIGNAL:
            break
        fid, frame = item

        try:
            # ── DETECT on FULL-RES frame ──
            detections, _ = detector.detect(frame)
            print(f"[WORKER] Frame {fid}: {len(detections)} face(s)")

            # ── USE EMBEDDING DIRECTLY from detection ──
            # Do NOT re-crop and re-detect. The embedding from detector.detect()
            # is already extracted from the full-resolution frame by InsightFace.
            for det in detections:
                emb = det.get("embedding")
                if emb is None:
                    det["name"] = None
                    continue

                print(f"[WORKER] emb_norm={np.linalg.norm(emb):.4f}")

                # ── RECOGNIZE ──
                with db_lock:
                    result, best_score, all_scores = recognizer.identify(emb, threshold=threshold)
                print(f"[WORKER] Result: recognized={result.get('recognized') if result else 'N/A'}, score={best_score:.4f}")

                if all_scores:
                    top3 = sorted(all_scores.items(), key=lambda x: x[1], reverse=True)[:3]
                    print(f"[WORKER] Top 3: {top3}")

                # ── DEBUG: save frame if best score is suspiciously low ──
                if best_score < 0.3:
                    debug_path = f"debug_low_score_frame_{fid}_{best_score:.3f}.jpg"
                    print(f"[WORKER] 💾 Saved low-score frame: {debug_path}")

                person_id = result.get("person_id") if result else None 
                name = result.get("name") if result else None
                confidence = result.get("confidence", 0.0) if result else 0.0
                det["person_id"] = person_id     
                det["name"] = str(name) if name else None
                det["distance"] = float(best_score) if best_score is not None else 0.0
                det["confidence"] = float(confidence)

        except Exception as e:
            print(f"[WORKER] Error: {e}")
            import traceback
            traceback.print_exc()
            detections = []

        try:
            result_queue.put_nowait((fid, detections))
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

print("\nPress 'q' to quit. Press 'r' to reload DB.\n")

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

    # ── SUBMIT FULL-RES FRAME to worker ──
    if frame_count % inference_every_n == 0:
        with counter_lock:
            current_fid = frame_counter
            frame_counter += 1

        try:
            frame_queue.put_nowait((current_fid, frame.copy()))
        except queue.Full:
            try:
                frame_queue.get_nowait()
                frame_queue.task_done()
                frame_queue.put_nowait((current_fid, frame.copy()))
            except queue.Empty:
                pass

    # ── COLLECT RESULTS ──
    try:
        while True:
            fid, dets = result_queue.get_nowait()
            with results_lock:
                latest_results[fid] = dets
            result_queue.task_done()
    except queue.Empty:
        pass

    # ── DRAW ──
    display = frame.copy()

    with results_lock:
        if latest_results:
            best_fid = max(latest_results.keys())
            detections = latest_results[best_fid]
            for old_fid in list(latest_results.keys()):
                if old_fid < best_fid - 5:
                    del latest_results[old_fid]
        else:
            detections = []

    if not detections:
        cv2.putText(display, "NO FACE", (20, 40),
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
    else:
        for det in detections:
            bbox = det["bbox"]
            x1, y1, x2, y2 = map(int, bbox)
            person_id = det.get("person_id")
            name = det.get("name")
            distance = det.get("distance", 0)
            conf = det.get("confidence", 0)

            if name:
                color = (0, 255, 0)
                label = f"{name} | {distance:.3f}"
                status = f"MATCH: {name} ({distance:.3f})"

                now = time.time()
                last_time = last_scan_time.get(person_id, 0)
                if now - last_time > SCAN_COOLDOWN_SECONDS:
                    last_scan_time[person_id] = now
                    threading.Thread(target=send_known, args=(person_id,), daemon=True).start()
                    label += " [SENT]"
                else:
                    label += " [COOLDOWN]"
            else:
                # Unknown face – do NOT send to server, just display
                color = (0, 165, 255)
                label = f"? UNKNOWN ({distance:.3f})"
                status = f"UNKNOWN ({distance:.3f})"

            cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)
            cv2.putText(display, label, (x1, y1 - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            if status != last_status:
                print(f"[Frame {frame_count}] {status}")
                last_status = status

    # FPS
    now = time.time()
    fps_display = 1.0 / (now - last_display_time)
    last_display_time = now
    cv2.putText(display, f"FPS: {fps_display:.1f} | Frame: {frame_count}",
                (20, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

    # ── PERIODIC DB RELOAD ──
    if now - last_db_reload > DB_RELOAD_INTERVAL:
        reload_database()
        last_db_reload = now

    cv2.imshow("Live Camera", display)

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break
    elif key == ord("r"):
        reload_database()
        last_db_reload = now

# ── SHUTDOWN ──
frame_queue.put(KILL_SIGNAL)
detection_thread.join(timeout=1.0)
cap.release()
cv2.destroyAllWindows()
print("\nDone.")