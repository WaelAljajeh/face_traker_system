#!/usr/bin/env python3
"""
Live Camera + Flask Server Client
==================================
Optimised for ONVIF/IP cameras (RTSP/HTTP) with frame scaling,
low latency (buffersize=1), auto-reconnect, and server integration.
"""

import sys
import os
import cv2
import numpy as np
import time
import threading
import queue
import requests
import atexit
import signal


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import Config
from utils.config import get_appdata_dir
from core import FaceDetector, FaceRecognizer
from models.database import init_database
from services.database_service import DatabaseService
from services.vector_database import FAISSVectorDB
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
if getattr(sys, 'frozen', False):
    os.chdir(sys._MEIPASS)

print("=" * 60)
print("LIVE CAMERA + SERVER CLIENT")
print("=" * 60)

config = Config.load("config.yaml")
recognition_cfg = config.get_section("recognition")
threshold = recognition_cfg.get("similarity_threshold", 0.45)

# ── PERFORMANCE: Smaller det_size + skip frames ──
perf_cfg = config.get_section("performance") or {}
inference_every_n = perf_cfg.get("inference_every_n_frames", 3)
frame_scale = perf_cfg.get("frame_scale", 0.75)

insight_cfg = config.get_section("insightface") or {}
model_name = "buffalo_l"

# ── SERVER CONFIG ──
server_cfg = config.get_section("server") or {}
SERVER_URL = server_cfg.get("url", "http://localhost:8000")
SERVER_TIMEOUT = server_cfg.get("timeout", 10)

# ── DATABASE PATH (APPDATA folder) ──
DB_PATH = os.path.join(get_appdata_dir(), "face_attendance.db")

# ── INITIALIZE DATABASE ──
engine, SessionLocal = init_database(DB_PATH)
db_service = DatabaseService(SessionLocal)
vector_db = FAISSVectorDB(embedding_dim=512)

# ── INITIALIZE AI MODELS ──
detector = FaceDetector(
    model_name=model_name,
    det_size=(640, 640),
    det_thresh=0.5,
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
print(f"det_size: 640x640 | frame_skip: {inference_every_n} | model: {model_name}")
print(f"Server: {SERVER_URL}")
print(f"DB: Loaded {len(recognizer.database)} embeddings")

# ─────────────────────────────────────────────────────────────
# THREADING SETUP
# ─────────────────────────────────────────────────────────────

frame_queue = queue.Queue(maxsize=2)
result_queue = queue.Queue()
capture_queue = queue.Queue(maxsize=1)
latest_results = {}
results_lock = threading.Lock()
capture_lock = threading.Lock()
frame_counter = 0
counter_lock = threading.Lock()
KILL_SIGNAL = None
CAPTURE_KILL = threading.Event()

last_scan_time = {}
SCAN_COOLDOWN_SECONDS = 8

# ── PAUSE / RESUME (handled by background thread) ──
paused = False
_pause_mutex = threading.Lock()
cap = None 
capture_thread = None # Camera handle, release/re-acquire during pause

# ── DB RELOAD SYNC ──
db_lock = threading.Lock()
last_db_reload = time.time()
DB_RELOAD_INTERVAL = 60  # seconds
_reload_requested = False
session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

no_retry_session = requests.Session()
no_retry_adapter = HTTPAdapter(max_retries=0)
no_retry_session.mount("http://", no_retry_adapter)
no_retry_session.mount("https://", no_retry_adapter)

def pause_status_worker():
    """Background thread: polls server for camera pause state without blocking the main loop."""
    while not CAPTURE_KILL.is_set():
        try:
            resp = no_retry_session.get(f"{SERVER_URL}/camera/status", timeout=2)
            new_paused = resp.status_code == 200 and resp.json().get("paused", False)
            with _pause_mutex:
                global paused
                if new_paused != paused:
                    paused = new_paused
                    if paused:
                        release_camera()
                        print("[PAUSE] Camera released")
                    else:
                        if reopen_camera():
                            print("[PAUSE] Camera resumed")
                            try:
                                while True:
                                    frame_queue.get_nowait()
                                    frame_queue.task_done()
                            except queue.Empty:
                                pass
                            try:
                                while True:
                                    result_queue.get_nowait()
                                    result_queue.task_done()
                            except queue.Empty:
                                pass
                            with results_lock:
                                latest_results.clear()
                        else:
                            print("[PAUSE] Failed to re-acquire camera")
                            paused = True
        except Exception:
            pass
        CAPTURE_KILL.wait(3)


def release_camera():
    global cap
    if cap is not None and cap.isOpened():
        cap.release()
        cap = None
        print("[CAMERA] Released")

def reopen_camera():
    global cap
    release_camera()
    time.sleep(0.8)
    # --- IP CAMERA OPTIMISATION: do not use CAP_DSHOW for network streams ---
    try:
        # On Windows, CAP_DSHOW may fail for RTSP; fallback to default (FFMPEG)
        new_cap = cv2.VideoCapture(device_id, cv2.CAP_FFMPEG)
    except Exception:
        new_cap = cv2.VideoCapture(device_id)
    new_cap.set(cv2.CAP_PROP_FRAME_WIDTH, camera_cfg.get("width", 640))
    new_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, camera_cfg.get("height", 480))
    new_cap.set(cv2.CAP_PROP_FPS, camera_cfg.get("fps", 15))
    # --- CRITICAL: reduce internal buffer to cut latency ---
    new_cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    new_cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000)
    new_cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000)
    if not new_cap.isOpened():
        print(f"[CAMERA] Failed to open camera {device_id}")
        return False
    # warmup
    for _ in range(5):
        new_cap.read()
    cap = new_cap
    print("[CAMERA] Re-acquired")
    return True

def capture_worker():
    """Dedicated capture thread: reads ONVIF/RTSP frames without blocking display."""
    while not CAPTURE_KILL.is_set():
        if cap is None or not cap.isOpened():
            CAPTURE_KILL.wait(0.05)
            continue
        try:
            ret, frame = cap.read()
        except Exception:
            CAPTURE_KILL.wait(0.05)
            continue
        if not ret:
            CAPTURE_KILL.wait(0.05)
            continue
        with capture_lock:
            while not capture_queue.empty():
                try:
                    capture_queue.get_nowait()
                except queue.Empty:
                    break
            try:
                capture_queue.put_nowait(frame)
            except queue.Full:
                pass

def shutdown_handler(signum=None, frame=None):
    print("\n[SHUTDOWN] Received signal, cleaning up...")
    global KILL_SIGNAL
    if KILL_SIGNAL is None:
        KILL_SIGNAL = True
        CAPTURE_KILL.set()
        frame_queue.put(KILL_SIGNAL)
        detection_thread.join(timeout=2.0)
        if capture_thread is not None:
         capture_thread.join(timeout=2.0)
        release_camera()
        cv2.destroyAllWindows()
    print("[SHUTDOWN] Done.")
    sys.exit(0)

atexit.register(shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

def send_known(member_id):
    try:
        resp = no_retry_session.post(
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

            engine, SessionLocal = init_database(DB_PATH)
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
    """Background thread: runs AI on frames."""
    while True:
        item = frame_queue.get()
        if item is KILL_SIGNAL:
            break
        fid, frame = item

        try:
            detections, _ = detector.detect(frame)

            for det in detections:
                emb = det.get("embedding")
                if emb is None:
                    det["name"] = None
                    continue

                result, best_score, all_scores = recognizer.identify(emb, threshold=threshold)

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

pause_thread = threading.Thread(target=pause_status_worker, daemon=True)
pause_thread.start()

# ─────────────────────────────────────────────────────────────
# CAPTURE THREAD
# ─────────────────────────────────────────────────────────────

# --- IP CAMERA: initialise with low buffering and appropriate backend ---
try:
    cap = cv2.VideoCapture(device_id, cv2.CAP_FFMPEG)
except Exception:
    cap = cv2.VideoCapture(device_id)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, camera_cfg.get("width", 640))
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, camera_cfg.get("height", 480))
cap.set(cv2.CAP_PROP_FPS, 15)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # <--- reduces lag
cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000)
cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000)

if not cap or not cap.isOpened():
    print(f"Cannot open camera {device_id}")
    sys.exit(1)

capture_thread = threading.Thread(target=capture_worker, daemon=True)
capture_thread.start()
time.sleep(0.5)  # let capture buffer fill

# ─────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────

print("\nPress 'q' to quit. Press 'r' to reload DB.\n")

frame_count = 0
last_status = ""
last_display_time = time.time()
fps_display = 0
while True:
    frame_count += 1

    # ── CHECK PAUSE STATUS (set by background thread) ──
    with _pause_mutex:
        is_paused = paused

    # ── WHEN PAUSED ──
    if is_paused:
        pause_frame = np.zeros((camera_cfg.get("height", 480), camera_cfg.get("width", 640), 3), dtype=np.uint8)
        cv2.putText(pause_frame, "PAUSED", (200, 240),
                    cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 3)
        cv2.putText(pause_frame, "Press 'q' to quit", (20, pause_frame.shape[0] - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.imshow("Live Camera", pause_frame)
        key = cv2.waitKey(100) & 0xFF
        if key == ord("q"):
            break
        continue

    try:
        frame = capture_queue.get_nowait()
    except queue.Empty:
        cv2.waitKey(5)
        continue

    h, w = frame.shape[:2]

    # ── SUBMIT FULL-RES FRAME to worker ──
    if frame_count % inference_every_n == 0:
        with counter_lock:
            current_fid = frame_counter
            frame_counter += 1

        try:
            frame_queue.put_nowait((current_fid, frame))
        except queue.Full:
            try:
                frame_queue.get_nowait()
                frame_queue.task_done()
                frame_queue.put_nowait((current_fid, frame))
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
                last_status = status

    # FPS
    now = time.time()
    fps_display = 1.0 / (now - last_display_time)
    last_display_time = now
    cv2.putText(display, f"FPS: {fps_display:.1f} | Frame: {frame_count}",
                (20, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

    # ── PERIODIC DB RELOAD (triggered in background thread) ──
    if now - last_db_reload > DB_RELOAD_INTERVAL:
        _reload_requested = True
        last_db_reload = now
    if _reload_requested:
        _reload_requested = False
        threading.Thread(target=reload_database, daemon=True).start()

    cv2.imshow("Live Camera", display)

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break
    elif key == ord("r"):
        print("[DB] Manual reload requested")
        threading.Thread(target=reload_database, daemon=True).start()

# ── SHUTDOWN ──
shutdown_handler()