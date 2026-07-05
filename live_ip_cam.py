#!/usr/bin/env python3
"""
Live Camera + Flask Server Client (Multi‑Camera)
With auto‑reconnect. Uses URLs exactly as provided in config.
Fixed: Bounding boxes are now correctly aligned regardless of display resize.
       RTSP streams use TCP transport and minimal buffering for low latency.
       Optional per‑camera detection scaling to reduce CPU load.
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
import subprocess

# ── ONVIF audio player (optional) ─────────────────────────────
try:
    from onvif import ONVIFCamera
    ONVIF_AVAILABLE = True
except ImportError:
    ONVIF_AVAILABLE = False

class ONVIFAudioPlayer:
    def __init__(self, ip, port=80, user="admin", password="admin", wsdl_dir="./wsdl"):
        self.ip = ip
        self.port = port
        self.user = user
        self.password = password
        self.wsdl_dir = wsdl_dir
        self.camera = None
        self.media = None
        self.profile_token = None
        self.backchannel_uri = None
        self.sample_rate = 8000
        self.codec = 'pcm_alaw'
        self._initialized = False
        self._ffmpeg_process = None
        self._lock = threading.Lock()

    def initialize(self):
        if self._initialized:
            return True
        if not ONVIF_AVAILABLE:
            return False
        try:
            self.camera = ONVIFCamera(self.ip, self.port, self.user, self.password, self.wsdl_dir)
            self.media = self.camera.create_media_service()
            profiles = self.media.GetProfiles()
            if not profiles:
                return False
            self.profile_token = profiles[0].token
            try:
                audio_configs = self.media.GetAudioOutputConfigurations()
                if audio_configs:
                    cfg = audio_configs[0]
                    if hasattr(cfg, 'Codec'):
                        codec = cfg.Codec.lower()
                        if 'g711' in codec or 'alaw' in codec:
                            self.codec = 'pcm_alaw'
                        elif 'ulaw' in codec:
                            self.codec = 'pcm_mulaw'
                    if hasattr(cfg, 'SampleRate'):
                        self.sample_rate = cfg.SampleRate
            except:
                pass
            self.backchannel_uri = f"rtsp://{self.ip}:{self.port}/onvif/backchannel"
            self._initialized = True
            return True
        except Exception as e:
            print(f"[ONVIF] Init error: {e}")
            return False

    def _generate_tone_pcm(self, frequency=800, duration=5.0):
        t = np.linspace(0, duration, int(self.sample_rate * duration), endpoint=False)
        wave = (np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)
        return wave.tobytes()

    def beep(self, frequency=800, duration=5.0, blocking=False):
        if not self._initialized and not self.initialize():
            return False
        self.stop()
        pcm = self._generate_tone_pcm(frequency, duration)
        cmd = [
            "ffmpeg", "-re", "-f", "s16le",
            "-ar", str(self.sample_rate), "-ac", "1", "-i", "pipe:0",
            "-acodec", self.codec, "-ar", str(self.sample_rate), "-ac", "1",
            "-f", "rtsp", self.backchannel_uri
        ]
        try:
            self._ffmpeg_process = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self._ffmpeg_process.stdin.write(pcm)
            self._ffmpeg_process.stdin.close()
            if not blocking:
                threading.Thread(target=lambda: self._ffmpeg_process.wait(), daemon=True).start()
            else:
                self._ffmpeg_process.wait()
            return True
        except Exception as e:
            print(f"[ONVIF] Stream error: {e}")
            return False

    def stop(self):
        with self._lock:
            if self._ffmpeg_process:
                self._ffmpeg_process.terminate()
                self._ffmpeg_process = None

    @staticmethod
    def beep_fallback(frequency=800, duration=0.3):
        try:
            import winsound
            winsound.Beep(frequency, int(duration * 1000))
        except ImportError:
            print('\a', end='', flush=True)

# ── Imports ─────────────────────────────────────────────────────
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
print("LIVE CAMERA + SERVER CLIENT (Multi‑Camera)")
print("=" * 60)

# ── Load config ─────────────────────────────────────────────────
config = Config.load("config.yaml")

recognition_cfg = config.get_section("recognition")
threshold = recognition_cfg.get("similarity_threshold", 0.45)

server_cfg = config.get_section("server") or {}
SERVER_URL = server_cfg.get("url", "http://localhost:8000")
SERVER_TIMEOUT = server_cfg.get("timeout", 10)

# ── Database ────────────────────────────────────────────────────
DB_PATH = os.path.join(get_appdata_dir(), "face_attendance.db")
engine, SessionLocal = init_database(DB_PATH)
db_service = DatabaseService(SessionLocal)
vector_db = FAISSVectorDB(embedding_dim=512)

detector = FaceDetector(model_name="buffalo_l", det_size=(640, 640), det_thresh=0.5, confidence_threshold=0.5)
recognizer = FaceRecognizer(db_service=db_service, vector_db=vector_db, normalize=True)

# ── Read camera list ────────────────────────────────────────────
cameras_config = config.get("cameras")
if not cameras_config:
    features = config.get_section("features") or {}
    cameras_config = features.get("cameras")

if not cameras_config:
    camera_cfg = config.get_section("camera")
    if camera_cfg:
        cameras_config = [{
            "id": "default",
            "source": camera_cfg.get("source", 0),
            "width": camera_cfg.get("width", 640),
            "height": camera_cfg.get("height", 480),
            "fps": camera_cfg.get("fps", 15),
            "frame_skip": camera_cfg.get("frame_skip", 1)
        }]
    else:
        print("[ERROR] No camera configuration found.")
        sys.exit(1)

print(f"Cameras: {[c['id'] for c in cameras_config]}")
print(f"Threshold: {threshold}")
print(f"Server: {SERVER_URL}")
print(f"DB: {len(recognizer.database)} embeddings loaded")

# ── ONVIF Audio ─────────────────────────────────────────────────
audio_player = None
onvif_cfg = config.get_section("onvif") or {}
if onvif_cfg.get("enabled", False):
    try:
        audio_player = ONVIFAudioPlayer(
            ip=onvif_cfg.get("ip"), port=onvif_cfg.get("port", 80),
            user=onvif_cfg.get("username", "admin"), password=onvif_cfg.get("password", "admin"),
            wsdl_dir=onvif_cfg.get("wsdl_dir", "./wsdl")
        )
        if audio_player.initialize():
            print("[AUDIO] ONVIF ready")
        else:
            audio_player = None
    except Exception as e:
        print(f"[AUDIO] ONVIF error: {e}")
        audio_player = None

# ── Helper to identify webcams ─────────────────────────────────
def is_webcam_source(source):
    """Return True if source is a local webcam (int or digit string)."""
    if isinstance(source, int):
        return True
    if isinstance(source, str):
        return source.isdigit()
    return False

# ── Global state ────────────────────────────────────────────────
camera_data = {}
CAPTURE_KILL = threading.Event()
KILL_SIGNAL = None
last_scan_time = {}
SCAN_COOLDOWN_SECONDS = 8
db_lock = threading.Lock()
last_db_reload = time.time()
DB_RELOAD_INTERVAL = 60
_reload_requested = False
paused = False
_pause_mutex = threading.Lock()

session = requests.Session()
retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry)
session.mount("http://", adapter)
session.mount("https://", adapter)

no_retry = requests.Session()
no_retry.mount("http://", HTTPAdapter(max_retries=0))
no_retry.mount("https://", HTTPAdapter(max_retries=0))

# ── Server send ─────────────────────────────────────────────────
def send_known(member_id):
    try:
        resp = no_retry.post(f"{SERVER_URL}/scan", json={"member_id": str(member_id)}, timeout=SERVER_TIMEOUT)
        if resp.status_code == 200:
            print(f"  [SERVER] Known scan: {member_id}")
            return True
        else:
            print(f"  [SERVER] Error {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"  [SERVER] Failed: {e}")
    return False

# ── DB reload ─────────────────────────────────────────────────
def reload_database():
    global engine, db_service, vector_db, recognizer
    with db_lock:
        print("[DB] Reloading...")
        try:
            if engine:
                engine.dispose()
            engine, SessionLocal = init_database(DB_PATH)
            db_service = DatabaseService(SessionLocal)
            vector_db = FAISSVectorDB(embedding_dim=512)
            recognizer = FaceRecognizer(db_service=db_service, vector_db=vector_db, normalize=True)
            print(f"[DB] Reloaded. {len(recognizer.database)} embeddings")
            return True
        except Exception as e:
            print(f"[DB] Reload failed: {e}")
            import traceback
            traceback.print_exc()
            return False

# ── Improved camera opener ──────────────────────────────────────
def open_camera_with_retry(cam_cfg):
    source = cam_cfg["source"]
    width = cam_cfg.get("width", 640)
    height = cam_cfg.get("height", 480)
    fps = cam_cfg.get("fps", 15)

    is_webcam = is_webcam_source(source)
    if is_webcam:
        if isinstance(source, str) and source.isdigit():
            source = int(source)

    # Build list of backends
    backends = []
    if sys.platform == "win32" and is_webcam:
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
    else:
        backends = [cv2.CAP_FFMPEG, cv2.CAP_ANY]

    # For RTSP, we try TCP first (more stable), then UDP as fallback
    urls_to_try = []
    if isinstance(source, str) and source.startswith("rtsp://"):
        # Add TCP transport
        tcp_url = source
        if "rtsp_transport" not in tcp_url:
            tcp_url = tcp_url + ("&rtsp_transport=tcp" if "?" in tcp_url else "?rtsp_transport=tcp")
        urls_to_try.append(tcp_url)
        # Also add UDP (as fallback)
        udp_url = source
        if "rtsp_transport" not in udp_url:
            udp_url = udp_url + ("&rtsp_transport=udp" if "?" in udp_url else "?rtsp_transport=udp")
        urls_to_try.append(udp_url)
    else:
        urls_to_try = [source]

    for url in urls_to_try:
        for backend in backends:
            print(f"[CAMERA] Trying source: {url} with backend {backend}")
            cap = cv2.VideoCapture(url, backend)
            if not cap.isOpened():
                cap.release()
                continue

            # Set properties (ignore errors)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            cap.set(cv2.CAP_PROP_FPS, fps)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)    # minimal buffer for low latency
            try:
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
            except:
                pass

            # Test read
            for _ in range(3):
                ret, frame = cap.read()
                if ret and frame is not None:
                    print(f"[CAMERA] Opened successfully: {url} (backend {backend})")
                    return cap
                time.sleep(0.1)

            cap.release()

    print(f"[CAMERA] Failed to open: {source} after all attempts.")
    return None

# ── Capture worker ────────────────────────────────────────────
def capture_worker(cam_id, cap, capture_queue, kill_event, cam_cfg):
    global paused
    while not kill_event.is_set():
        with _pause_mutex:
            is_paused = paused
        is_webcam = is_webcam_source(cam_cfg["source"])

        if is_paused and is_webcam:
            if cap is not None:
                cap.release()
                cap = None
                camera_data[cam_id]["cap"] = None
                print(f"[CAMERA {cam_id}] Released for pause.")
            kill_event.wait(0.5)
            continue

        if cap is None:
            print(f"[CAMERA {cam_id}] (Re)connecting...")
            new_cap = open_camera_with_retry(cam_cfg)
            if new_cap:
                cap = new_cap
                camera_data[cam_id]["cap"] = cap
                print(f"[CAMERA {cam_id}] Reconnected.")
            else:
                kill_event.wait(1.0)
                continue

        ret, frame = cap.read()
        if not ret:
            print(f"[CAMERA {cam_id}] Read failed, releasing...")
            cap.release()
            cap = None
            camera_data[cam_id]["cap"] = None
            kill_event.wait(0.2)
            continue

        # Store original dimensions (for later scaling of boxes)
        orig_h, orig_w = frame.shape[:2]
        with camera_data[cam_id]["frame_lock"]:
            camera_data[cam_id]["latest_frame"] = frame
            camera_data[cam_id]["orig_w"] = orig_w
            camera_data[cam_id]["orig_h"] = orig_h

        frame_skip = cam_cfg.get("frame_skip", 1)
        camera_data[cam_id]["frame_counter"] += 1
        if camera_data[cam_id]["frame_counter"] % frame_skip == 0:
            # Optionally scale down before detection to reduce CPU load
            detection_scale = cam_cfg.get("detection_scale", 1.0)
            if detection_scale != 1.0:
                new_w = int(orig_w * detection_scale)
                new_h = int(orig_h * detection_scale)
                frame_scaled = cv2.resize(frame, (new_w, new_h))
                with camera_data[cam_id]["frame_lock"]:
                    camera_data[cam_id]["det_scale"] = detection_scale
                    camera_data[cam_id]["det_w"] = new_w
                    camera_data[cam_id]["det_h"] = new_h
            else:
                frame_scaled = frame
                with camera_data[cam_id]["frame_lock"]:
                    camera_data[cam_id]["det_scale"] = 1.0
                    camera_data[cam_id]["det_w"] = orig_w
                    camera_data[cam_id]["det_h"] = orig_h

            try:
                while True:
                    capture_queue.get_nowait()
                    capture_queue.task_done()
            except queue.Empty:
                pass
            try:
                capture_queue.put_nowait(frame_scaled)
            except queue.Full:
                pass

        kill_event.wait(0.001)

# ── Detection worker ────────────────────────────────────────────
def detection_worker(cam_id, capture_queue, result_queue, kill_event):
    while not kill_event.is_set():
        try:
            frame = capture_queue.get(timeout=0.1)
        except queue.Empty:
            continue
        if frame is None:
            break

        # Get the detection scale factors from camera_data
        with camera_data[cam_id]["frame_lock"]:
            det_scale = camera_data[cam_id].get("det_scale", 1.0)
            det_w = camera_data[cam_id].get("det_w", frame.shape[1])
            det_h = camera_data[cam_id].get("det_h", frame.shape[0])

        try:
            detections, _ = detector.detect(frame)
            # Scale boxes back to original frame coordinates if detection was downscaled
            if det_scale != 1.0:
                for det in detections:
                    x1, y1, x2, y2 = det["bbox"]
                    det["bbox"] = [x1 / det_scale, y1 / det_scale, x2 / det_scale, y2 / det_scale]

            for det in detections:
                emb = det.get("embedding")
                if emb is None:
                    det["name"] = None
                    continue
                result, best_score, _ = recognizer.identify(emb, threshold=threshold)
                person_id = result.get("person_id") if result else None
                name = result.get("name") if result else None
                det["person_id"] = person_id
                det["name"] = str(name) if name else None
                det["distance"] = float(best_score) if best_score is not None else 0.0
                det["confidence"] = float(result.get("confidence", 0.0)) if result else 0.0

                if name:
                    now = time.time()
                    if now - last_scan_time.get(person_id, 0) > SCAN_COOLDOWN_SECONDS:
                        last_scan_time[person_id] = now
                        def beep_and_send():
                            if audio_player:
                                audio_player.beep(frequency=800, duration=5.0, blocking=False)
                            else:
                                ONVIFAudioPlayer.beep_fallback()
                            send_known(person_id)
                        threading.Thread(target=beep_and_send, daemon=True).start()
        except Exception as e:
            print(f"[WORKER {cam_id}] Error: {e}")
            detections = []

        try:
            result_queue.put_nowait((time.time(), detections))
        except queue.Full:
            pass
        capture_queue.task_done()

# ── Pause worker ──────────────────────────────────────────────
def pause_status_worker():
    global paused
    while not CAPTURE_KILL.is_set():
        try:
            resp = no_retry.get(f"{SERVER_URL}/camera/status", timeout=2)
            new_paused = resp.status_code == 200 and resp.json().get("paused", False)
            with _pause_mutex:
                if new_paused != paused:
                    paused = new_paused
                    if paused:
                        print("[PAUSE] Paused (webcam will freeze, IP cam keeps running)")
                    else:
                        print("[PAUSE] Resumed (webcam continues)")
        except:
            pass
        CAPTURE_KILL.wait(3)

# ── Shutdown ────────────────────────────────────────────────────
def shutdown_handler(signum=None, frame=None):
    print("\n[SHUTDOWN] Cleaning up...")
    global KILL_SIGNAL
    if KILL_SIGNAL is None:
        KILL_SIGNAL = True
        CAPTURE_KILL.set()
        for data in camera_data.values():
            if data["detection_thread"]:
                data["detection_thread"].join(timeout=2)
            if data["capture_thread"]:
                data["capture_thread"].join(timeout=2)
            if data["cap"]:
                data["cap"].release()
        if audio_player:
            audio_player.stop()
        cv2.destroyAllWindows()
    print("[SHUTDOWN] Done.")
    sys.exit(0)

atexit.register(shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

# ═══════════════════════════════════════════════════════════════
# INITIALISE — DO NOT BLOCK ON CAMERA OPEN
# ═══════════════════════════════════════════════════════════════
for cam_cfg in cameras_config:
    cam_id = cam_cfg["id"]
    print(f"Initialising camera: {cam_id} (source: {cam_cfg['source']})")

    cap = None
    print(f"[CAMERA] {cam_id} will connect in background.")

    capture_q = queue.Queue(maxsize=1)
    result_q = queue.Queue()

    data = {
        "cfg": cam_cfg,
        "cap": cap,
        "capture_queue": capture_q,
        "result_queue": result_q,
        "frame_counter": 0,
        "latest_frame": None,
        "frame_lock": threading.Lock(),
        "latest_results": {},
        "results_lock": threading.Lock(),
        "capture_thread": None,
        "detection_thread": None,
        "orig_w": 0,
        "orig_h": 0,
        "det_scale": 1.0,
        "det_w": 0,
        "det_h": 0,
    }
    camera_data[cam_id] = data

    ct = threading.Thread(target=capture_worker, args=(cam_id, cap, capture_q, CAPTURE_KILL, cam_cfg), daemon=True)
    ct.start()
    data["capture_thread"] = ct

    dt = threading.Thread(target=detection_worker, args=(cam_id, capture_q, result_q, CAPTURE_KILL), daemon=True)
    dt.start()
    data["detection_thread"] = dt

if not camera_data:
    print("[ERROR] No cameras configured.")
    sys.exit(1)

pause_thread = threading.Thread(target=pause_status_worker, daemon=True)
pause_thread.start()

# ═══════════════════════════════════════════════════════════════
# MAIN DISPLAY LOOP — UI STARTS IMMEDIATELY, NEVER BLOCKS
# ═══════════════════════════════════════════════════════════════
print("\nPress 'q' to quit. Press 'r' to reload DB.\n")

cv2.namedWindow("Live Cameras", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Live Cameras", 1280, 480)

startup_frame = np.zeros((480, 640, 3), dtype=np.uint8)
cv2.putText(startup_frame, "Starting cameras...", (150, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
cv2.imshow("Live Cameras", startup_frame)
cv2.waitKey(1)
print("[UI] Window is open. Waiting for cameras...")

frame_count = 0
last_display_time = time.time()

while True:
    frame_count += 1
    with _pause_mutex:
        is_paused = paused

    display_frames = []
    for cam_id, data in camera_data.items():
        with data["frame_lock"]:
            frame = data["latest_frame"]
            orig_w = data.get("orig_w", 0)
            orig_h = data.get("orig_h", 0)

        h = data["cfg"].get("height", 480)
        w = data["cfg"].get("width", 640)

        if frame is None or orig_w == 0 or orig_h == 0:
            # Placeholder
            frame = np.zeros((h, w, 3), dtype=np.uint8)
            cv2.putText(frame, f"No feed ({cam_id})", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv2.putText(frame, "Connecting...", (20, 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)
            scale_x = 1.0
            scale_y = 1.0
        else:
            if frame.shape[0] != h or frame.shape[1] != w:
                frame = cv2.resize(frame, (w, h))
            scale_x = w / orig_w if orig_w > 0 else 1.0
            scale_y = h / orig_h if orig_h > 0 else 1.0

        # Pull detection results
        try:
            while True:
                ts, dets = data["result_queue"].get_nowait()
                with data["results_lock"]:
                    data["latest_results"][ts] = dets
                data["result_queue"].task_done()
        except queue.Empty:
            pass

        with data["results_lock"]:
            if data["latest_results"]:
                latest_ts = max(data["latest_results"].keys())
                detections = data["latest_results"][latest_ts]
                for old in list(data["latest_results"].keys()):
                    if old < latest_ts - 5:
                        del data["latest_results"][old]
            else:
                detections = []

        # Paused overlay for webcams
        with _pause_mutex:
            if is_paused and is_webcam_source(data["cfg"]["source"]):
                overlay = frame.copy()
                cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 0), -1)
                cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
                cv2.putText(frame, "PAUSED", (w//2 - 80, h//2),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3, cv2.LINE_AA)

        # Draw boxes with scaled coordinates
        if not detections:
            cv2.putText(frame, "NO FACE", (20, 120),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (128, 128, 128), 2)
        else:
            for det in detections:
                x1, y1, x2, y2 = map(int, det["bbox"])
                x1 = int(x1 * scale_x)
                y1 = int(y1 * scale_y)
                x2 = int(x2 * scale_x)
                y2 = int(y2 * scale_y)

                name = det.get("name")
                distance = det.get("distance", 0)
                if name:
                    color = (0, 255, 0)
                    label = f"{name} | {distance:.3f}"
                else:
                    color = (0, 165, 255)
                    label = f"? UNKNOWN ({distance:.3f})"
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame, label, (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        cv2.putText(frame, cam_id, (10, h - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        display_frames.append(frame)

    # Build display
    if display_frames:
        max_h = max(f.shape[0] for f in display_frames)
        resized = []
        for f in display_frames:
            if f.shape[0] != max_h:
                scale = max_h / f.shape[0]
                f = cv2.resize(f, (int(f.shape[1] * scale), max_h))
            resized.append(f)
        try:
            display = np.hstack(resized)
        except Exception as e:
            print(f"[UI] hstack error: {e}")
            display = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(display, "Display Error", (50, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
    else:
        display = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(display, "No cameras configured", (50, 240),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

    # Global FPS
    now = time.time()
    fps = 1.0 / (now - last_display_time) if now > last_display_time else 0
    last_display_time = now
    cv2.putText(display, f"FPS: {fps:.1f} | Frame: {frame_count}", (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    cv2.imshow("Live Cameras", display)

    # Auto DB reload
    if now - last_db_reload > DB_RELOAD_INTERVAL:
        _reload_requested = True
        last_db_reload = now
    if _reload_requested:
        _reload_requested = False
        threading.Thread(target=reload_database, daemon=True).start()

    key = cv2.waitKey(10) & 0xFF
    if key == ord("q"):
        break
    elif key == ord("r"):
        print("[DB] Manual reload requested")
        threading.Thread(target=reload_database, daemon=True).start()

shutdown_handler()