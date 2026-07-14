#!/usr/bin/env python3
"""
Live Camera + Flask Server Client (Multi‑Camera)
With auto‑reconnect. Uses URLs exactly as provided in config.
Fixed: Bounding boxes are now correctly aligned regardless of display resize.
       RTSP streams use TCP transport and minimal buffering for low latency.
       Optional per‑camera detection scaling to reduce CPU load.
FIXED: Pause/resume now works reliably for webcams – added release delay.
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
from core.quality import QualityFilter
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
min_stable_frames = recognition_cfg.get("min_stable_frames", 3)

server_cfg = config.get_section("server") or {}
SERVER_URL = server_cfg.get("url", "http://localhost:8000")
SERVER_TIMEOUT = server_cfg.get("timeout", 10)

# ── Database ────────────────────────────────────────────────────
DB_PATH = os.path.join(get_appdata_dir(), "face_attendance.db")
engine, SessionLocal = init_database(DB_PATH)
db_service = DatabaseService(SessionLocal)
vector_db = FAISSVectorDB(embedding_dim=512)

recognizer = FaceRecognizer(db_service=db_service, vector_db=vector_db, normalize=True)

# Read insightface / detector settings from config
insight_cfg = config.get_section("insightface") or {}
det_thresh = insight_cfg.get("det_threshold", 0.40)
confidence_threshold = insight_cfg.get("confidence_threshold", 0.55)
det_size = tuple(insight_cfg.get("det_size", [640, 640]))
detector = FaceDetector(model_name=insight_cfg.get("model_name", "buffalo_l"),
                        det_size=det_size, det_thresh=det_thresh,
                        confidence_threshold=confidence_threshold)
# Separate filter: reject detections below this confidence (higher than det_thresh)
MIN_DET_CONFIDENCE = confidence_threshold

quality_filter = QualityFilter(config.get_section("quality_filter") or {})

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
face_track_frames = {}  # person_id -> consecutive frame count (temporal consistency)
SCAN_COOLDOWN_SECONDS = 5

# ── Mode state (runtime-switchable) ────────────────────────────
current_mode = "accuracy"
current_min_stable_frames = min_stable_frames
current_similarity_threshold = threshold
current_blur_threshold = float(config.get("quality_filter.blur_threshold", 40.0))
current_min_face_size = int(config.get("quality_filter.min_face_size", 30))
current_cooldown = SCAN_COOLDOWN_SECONDS
_mode_mutex = threading.Lock()
MODE_POLL_INTERVAL = 3  # seconds

# ── Interactive settings ───────────────────────────────────────
show_settings_hud = True
SETTINGS_HELP = [
    ("H", "Toggle this help"),
    ("M", "Toggle speed/accuracy mode"),
    ("[/]", "Threshold -/+ 0.05"),
    ("{-}", "Min frames -/+ 1"),
    ("N/M", "Blur threshold -/+ 5"),
    ("B/V", "Min face size -/+ 5"),
    ("C/X", "Cooldown -/+ 1s"),
    ("R", "Reload DB"),
    ("Q", "Quit"),
]
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

# ── Mode helpers ────────────────────────────────────────────────
def get_mode_params():
    """Thread-safe read all current mode params."""
    with _mode_mutex:
        return {
            "min_stable_frames": current_min_stable_frames,
            "similarity_threshold": current_similarity_threshold,
            "mode": current_mode,
            "blur_threshold": current_blur_threshold,
            "min_face_size": current_min_face_size,
            "cooldown": current_cooldown,
        }

def set_mode_params(mode: str, min_frames: int, sim_threshold: float):
    """Thread-safe write current mode params."""
    global current_mode, current_min_stable_frames, current_similarity_threshold
    with _mode_mutex:
        old_mode = current_mode
        current_mode = mode
        current_min_stable_frames = min_frames
        current_similarity_threshold = sim_threshold
    print(f"[MODE] {old_mode} → {mode} (frames={min_frames}, threshold={sim_threshold:.2f})")

# ── Server send ─────────────────────────────────────────────────
def send_known(member_id, image_base64=None, phase="confirmed"):
    """Send known face scan to server with optional image and phase."""
    payload = {
        "member_id": str(member_id),
        "phase": phase,
    }
    if image_base64:
        payload["image_base64"] = image_base64
    try:
        resp = no_retry.post(f"{SERVER_URL}/scan", json=payload, timeout=SERVER_TIMEOUT)
        if resp.status_code == 200:
            print(f"  [SERVER] Known scan: {member_id} (phase={phase})")
            return True
        else:
            print(f"  [SERVER] Error {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"  [SERVER] Failed: {e}")
    return False

# ── Face crop to base64 ──────────────────────────────────────────
def face_to_base64(frame, bbox):
    """Crop face from frame using bbox [x1,y1,x2,y2] and return base64 jpeg."""
    import cv2, base64
    x1, y1, x2, y2 = map(int, bbox)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
    if x2 <= x1 or y2 <= y1:
        face_crop = frame
    else:
        face_crop = frame[y1:y2, x1:x2]
    if face_crop.size == 0:
        return None
    pad_x = int((x2 - x1) * 0.3)
    pad_y = int((y2 - y1) * 0.3)
    x1p, y1p = max(0, x1 - pad_x), max(0, y1 - pad_y)
    x2p, y2p = min(frame.shape[1], x2 + pad_x), min(frame.shape[0], y2 + pad_y)
    face_crop = frame[y1p:y2p, x1p:x2p]
    _, buf = cv2.imencode('.jpg', face_crop, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return base64.b64encode(buf).decode('utf-8')

def send_unknown(image_base64, face_quality=None, confidence=None, phase="pending"):
    """Send unknown face scan to server with image."""
    try:
        resp = no_retry.post(f"{SERVER_URL}/scan", json={
            "member_id": None,
            "image_base64": image_base64,
            "confidence": confidence,
            "face_quality": face_quality or "unknown",
            "phase": phase,
        }, timeout=SERVER_TIMEOUT)
        if resp.status_code == 200:
            print(f"  [SERVER] Unknown scan sent")
            return True
        else:
            print(f"  [SERVER] Unknown scan error {resp.status_code}")
    except Exception as e:
        print(f"  [SERVER] Unknown scan failed: {e}")
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

            # Test read – reduce retries to 1 for faster reconnect
            for _ in range(1):   # was 3, now 1
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

        # ============================================================
        # PAUSE: release camera if it's a webcam
        # ============================================================
        if is_paused and is_webcam:
            if cap is not None:
                cap.release()
                cap = None
                camera_data[cam_id]["cap"] = None
                print(f"[CAMERA {cam_id}] Released for pause.")
                # Wait a moment so the OS can free the camera handle
                time.sleep(0.3)
            # Sleep a bit to avoid busy loop, but react quickly to resume
            kill_event.wait(0.1)
            continue

        # ============================================================
        # RESUME: reconnect if camera is not open
        # ============================================================
        if cap is None:
            print(f"[CAMERA {cam_id}] (Re)connecting...")
            new_cap = open_camera_with_retry(cam_cfg)
            if new_cap:
                cap = new_cap
                camera_data[cam_id]["cap"] = cap
                print(f"[CAMERA {cam_id}] Reconnected.")
            else:
                # Wait a bit before retrying
                kill_event.wait(1.0)
                continue

        # Read frame
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
                # Layer 1: Detection confidence filter — rejects wall patterns / noise
                det_conf = float(det.get("confidence", 0.0))
                if det_conf < MIN_DET_CONFIDENCE:
                    det["name"] = None
                    det["quality_pass"] = False
                    continue

                # Layer 2: Landmark check — real faces have 5 facial landmarks
                if det.get("landmarks") is None:
                    det["name"] = None
                    det["quality_pass"] = False
                    continue

                emb = det.get("embedding")
                if emb is None:
                    det["name"] = None
                    continue
                mode_params = get_mode_params()
                current_threshold = mode_params["similarity_threshold"]
                result, best_score, _ = recognizer.identify(emb, threshold=current_threshold)
                person_id = result.get("person_id") if result else None
                name = result.get("name") if result else None
                det["person_id"] = person_id
                det["name"] = str(name) if name else None
                det["distance"] = float(best_score) if best_score is not None else 0.0
                det["confidence"] = float(result.get("confidence", 0.0)) if result else 0.0

                # Layer 3: Quality check on original frame
                with camera_data[cam_id]["frame_lock"]:
                    orig_frame = camera_data[cam_id].get("latest_frame")

                qc_pass = True
                if orig_frame is not None:
                    qc_pass, qc_score, qc_reasons = quality_filter.assess(orig_frame, det)
                    det["quality_pass"] = qc_pass
                else:
                    det["quality_pass"] = True

                # Encode face image once (reused for both known and unknown)
                face_b64 = None
                if orig_frame is not None and qc_pass:
                    face_b64 = face_to_base64(orig_frame, det["bbox"])

                if name and qc_pass:
                    # Temporal consistency: require N consecutive frames with same ID
                    face_track_frames[person_id] = face_track_frames.get(person_id, 0) + 1
                    consecutive = face_track_frames[person_id]

                    mode_params = get_mode_params()
                    min_stable = mode_params["min_stable_frames"]

                    if consecutive >= min_stable:
                        now = time.time()
                        if now - last_scan_time.get(person_id, 0) > SCAN_COOLDOWN_SECONDS:
                            last_scan_time[person_id] = now
                            def beep_and_send():
                                if audio_player:
                                    audio_player.beep(frequency=800, duration=5.0, blocking=False)
                                else:
                                    ONVIFAudioPlayer.beep_fallback()
                                send_known(person_id, image_base64=face_b64, phase="confirmed")
                            threading.Thread(target=beep_and_send, daemon=True).start()
                elif not name and qc_pass:
                    # Unknown face – send to server for review in Flutter
                    now = time.time()
                    cam_last = last_scan_time.get(f"unknown_{cam_id}", 0)
                    if now - cam_last > SCAN_COOLDOWN_SECONDS:
                        last_scan_time[f"unknown_{cam_id}"] = now
                        conf = det.get("confidence", 0.0)
                        def send_unk():
                            send_unknown(face_b64, confidence=float(conf), phase="pending")
                        threading.Thread(target=send_unk, daemon=True).start()
        except Exception as e:
            print(f"[WORKER {cam_id}] Error: {e}")
            detections = []

        # Reset consecutive counts for persons NOT seen in this frame
        seen_persons = {d.get("person_id") for d in detections if d.get("name")}
        for pid in list(face_track_frames.keys()):
            if pid is not None and pid not in seen_persons:
                face_track_frames.pop(pid, None)

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
            if resp.status_code == 200:
                new_paused = resp.json().get("paused", False)
                with _pause_mutex:
                    if new_paused != paused:
                        paused = new_paused
                        if paused:
                            print("[PAUSE] Paused (webcam released)")
                        else:
                            print("[PAUSE] Resumed (reconnecting...)")
        except Exception as e:
            # If server is unreachable, keep current state
            pass
        # Poll every 1 second for fast response
        CAPTURE_KILL.wait(1)

# ── Mode polling worker ────────────────────────────────────────
def mode_poll_worker():
    """Poll server for mode changes at runtime."""
    while not CAPTURE_KILL.is_set():
        try:
            resp = no_retry.get(f"{SERVER_URL}/api/mode", timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                new_mode = data.get("mode", current_mode)
                params = data.get("params", {})
                if new_mode != current_mode:
                    min_frames = int(params.get("recognition.min_stable_frames", current_min_stable_frames))
                    sim_thresh = float(params.get("recognition.similarity_threshold", current_similarity_threshold))
                    set_mode_params(new_mode, min_frames, sim_thresh)
        except Exception:
            pass
        CAPTURE_KILL.wait(MODE_POLL_INTERVAL)

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

mode_thread = threading.Thread(target=mode_poll_worker, daemon=True)
mode_thread.start()

# ── Interactive settings helpers ───────────────────────────────

def apply_settings_to_quality_filter():
    """Push current manual settings to the quality filter."""
    with _mode_mutex:
        bt = current_blur_threshold
        mfs = current_min_face_size
    quality_filter.apply_mode({
        "blur_threshold": bt,
        "min_face_size": mfs,
    })

def draw_settings_hud(frame, params):
    """Draw current settings as overlay on the frame."""
    lines = [
        f"MODE: {params['mode'].upper()}",
        f"Threshold: {params['similarity_threshold']:.2f}",
        f"Min frames: {params['min_stable_frames']}",
        f"Blur thr: {params['blur_threshold']:.0f}",
        f"Min face: {params['min_face_size']}px",
        f"Cooldown: {params['cooldown']}s",
    ]
    x, y_start = 10, 60
    line_h = 18
    overlay = frame.copy()
    cv2.rectangle(overlay, (x - 4, y_start - 4),
                  (x + 220, y_start + len(lines) * line_h + 4),
                  (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
    for i, line in enumerate(lines):
        cv2.putText(frame, line, (x, y_start + i * line_h + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (0, 255, 255) if i > 0 else (100, 255, 100), 1)

    # Draw help hint at bottom
    cv2.putText(frame, "H:settings | M:mode | [:thr- ]:thr+ | -:frames- =:frames+ | Q:quit",
                (10, frame.shape[0] - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1)


print("\n══════════════════════════════════════════════════")
print("  INTERACTIVE SETTINGS")
print("══════════════════════════════════════════════════")
print("  H          Toggle settings panel")
print("  M          Toggle speed / accuracy mode")
print("  [ / ]     Threshold  - / + 0.05")
print("  - / =     Min frames - / + 1")
print("  n / N     Blur thr   - / + 5")
print("  b / B     Min face   - / + 5px")
print("  c / C     Cooldown   - / + 1s")
print("  R          Reload database")
print("  Q          Quit")
print("══════════════════════════════════════════════════\n")

# ═══════════════════════════════════════════════════════════════
# MAIN DISPLAY LOOP — UI STARTS IMMEDIATELY, NEVER BLOCKS
# ═══════════════════════════════════════════════════════════════

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

    # Draw settings HUD overlay
    if show_settings_hud:
        p = get_mode_params()
        draw_settings_hud(display, p)

    cv2.imshow("Live Cameras", display)

    # Auto DB reload
    if now - last_db_reload > DB_RELOAD_INTERVAL:
        _reload_requested = True
        last_db_reload = now
    if _reload_requested:
        _reload_requested = False
        threading.Thread(target=reload_database, daemon=True).start()

    # ── Interactive keyboard controls ──
    key = cv2.waitKey(10) & 0xFF
    if key == ord("q"):
        break
    elif key == ord("r"):
        print("[DB] Manual reload requested")
        threading.Thread(target=reload_database, daemon=True).start()

    elif key == ord("h"):
        show_settings_hud = not show_settings_hud
        print(f"[SETTINGS] HUD {'ON' if show_settings_hud else 'OFF'}")

    elif key == ord("m"):
        with _mode_mutex:
            new_mode = "speed" if current_mode == "accuracy" else "accuracy"
        # Fetch mode params from server
        try:
            resp = no_retry.get(f"{SERVER_URL}/api/mode", timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                svr_mode = data.get("mode", new_mode)
                params = data.get("params", {})
                if svr_mode != new_mode:
                    # Server hasn't been told — set it
                    no_retry.post(f"{SERVER_URL}/api/mode",
                                  data={"mode": new_mode}, timeout=2)
                    resp2 = no_retry.get(f"{SERVER_URL}/api/mode", timeout=2)
                    if resp2.status_code == 200:
                        params = resp2.json().get("params", {})
                min_f = int(params.get("recognition.min_stable_frames", current_min_stable_frames))
                sim_t = float(params.get("recognition.similarity_threshold", current_similarity_threshold))
                set_mode_params(svr_mode, min_f, sim_t)
        except Exception as e:
            print(f"[SETTINGS] Failed to sync mode with server: {e}")
            # Fall back to local config
            import yaml
            with open("config.yaml", "r") as f:
                cfg = yaml.safe_load(f)
            profiles = cfg.get("modes", {})
            profile = profiles.get(new_mode, {})
            rec_cfg = profile.get("recognition", {})
            qf_cfg = profile.get("quality_filter", {})
            min_f = int(rec_cfg.get("min_stable_frames", current_min_stable_frames))
            sim_t = float(rec_cfg.get("similarity_threshold", current_similarity_threshold))
            bt = float(qf_cfg.get("blur_threshold", current_blur_threshold))
            mfs = int(qf_cfg.get("min_face_size", current_min_face_size))
            with _mode_mutex:
                current_mode = new_mode
                current_min_stable_frames = min_f
                current_similarity_threshold = sim_t
                current_blur_threshold = bt
                current_min_face_size = mfs
            apply_settings_to_quality_filter()
            print(f"[SETTINGS] Local mode → {new_mode}")

    elif key == ord("["):  # Threshold -0.05
        with _mode_mutex:
            current_similarity_threshold = max(0.10, current_similarity_threshold - 0.05)
            t = current_similarity_threshold
        print(f"[SETTINGS] Threshold = {t:.2f}")

    elif key == ord("]"):  # Threshold +0.05
        with _mode_mutex:
            current_similarity_threshold = min(0.95, current_similarity_threshold + 0.05)
            t = current_similarity_threshold
        print(f"[SETTINGS] Threshold = {t:.2f}")

    elif key == ord("-"):  # Min frames -1
        with _mode_mutex:
            current_min_stable_frames = max(1, current_min_stable_frames - 1)
            f = current_min_stable_frames
        print(f"[SETTINGS] Min stable frames = {f}")

    elif key == ord("="):  # Min frames +1
        with _mode_mutex:
            current_min_stable_frames = min(10, current_min_stable_frames + 1)
            f = current_min_stable_frames
        print(f"[SETTINGS] Min stable frames = {f}")

    elif key == ord("n"):  # Blur threshold -5
        with _mode_mutex:
            current_blur_threshold = max(5.0, current_blur_threshold - 5.0)
            bt = current_blur_threshold
        apply_settings_to_quality_filter()
        print(f"[SETTINGS] Blur threshold = {bt:.0f}")

    elif key == ord("N"):  # Blur threshold +5 (shift+N = Unicode 78)
        with _mode_mutex:
            current_blur_threshold = min(200.0, current_blur_threshold + 5.0)
            bt = current_blur_threshold
        apply_settings_to_quality_filter()
        print(f"[SETTINGS] Blur threshold = {bt:.0f}")

    elif key == ord("b"):  # Min face size -5
        with _mode_mutex:
            current_min_face_size = max(10, current_min_face_size - 5)
            mfs = current_min_face_size
        apply_settings_to_quality_filter()
        print(f"[SETTINGS] Min face size = {mfs}px")

    elif key == ord("B"):  # Min face size +5 (shift+B = Unicode 66)
        with _mode_mutex:
            current_min_face_size = min(200, current_min_face_size + 5)
            mfs = current_min_face_size
        apply_settings_to_quality_filter()
        print(f"[SETTINGS] Min face size = {mfs}px")

    elif key == ord("c"):  # Cooldown -1s
        with _mode_mutex:
            current_cooldown = max(0, current_cooldown - 1)
        SCAN_COOLDOWN_SECONDS = current_cooldown
        print(f"[SETTINGS] Cooldown = {SCAN_COOLDOWN_SECONDS}s")

    elif key == ord("C"):  # Cooldown +1s (shift+C = Unicode 67)
        with _mode_mutex:
            current_cooldown = min(30, current_cooldown + 1)
        SCAN_COOLDOWN_SECONDS = current_cooldown
        print(f"[SETTINGS] Cooldown = {SCAN_COOLDOWN_SECONDS}s")

shutdown_handler()