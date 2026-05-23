# ============================================================
# CAMERA SERVICE - IP Camera and Webcam Handling
# ============================================================
# Handles:
# - Continuous frame capture
# - RTSP/IP camera support
# - Reconnection logic
# - Buffering and frame timing
# - Graceful degradation

import cv2
import threading
import time
import queue
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class CameraReader:
    """
    Dedicated camera reader thread.
    
    Continuously captures frames in background and maintains
    a latest-frame buffer for low-latency streaming.
    """
    
    def __init__(self, device_id: int = 0, width: int = 640, height: int = 480,
                 fps: int = 30, buffer_size: int = 1,
                 reconnect_timeout: int = 5, reconnect_max_attempts: int = 3):
        """
        Initialize camera reader.
        
        Args:
            device_id: Camera index (0) or RTSP URL
            width: Frame width
            height: Frame height
            fps: Target frames per second
            buffer_size: Queue size (1 = latest only)
            reconnect_timeout: Seconds before reconnect attempt
            reconnect_max_attempts: Max reconnect tries before giving up
        """
        self.device_id = device_id
        self.width = width
        self.height = height
        self.fps = fps
        self.frame_delay = 1.0 / fps if fps > 0 else 0.033
        self.buffer_size = buffer_size
        self.reconnect_timeout = reconnect_timeout
        self.reconnect_max_attempts = reconnect_max_attempts
        
        self.frame_queue = queue.Queue(maxsize=buffer_size)
        self.latest_frame: Optional[Tuple] = None  # (frame, timestamp)
        self.running = False
        self.connected = False
        self.frame_count = 0
        self.drop_count = 0
        
        self.reader_thread = None
        self.lock = threading.Lock()
    
    def start(self):
        """Start camera reader thread."""
        if self.running:
            return
        
        self.running = True
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()
        logger.info(f"[CAMERA] Reader started (device: {self.device_id})")
    
    def stop(self):
        """Stop camera reader thread."""
        self.running = False
        if self.reader_thread:
            self.reader_thread.join(timeout=2)
        logger.info("[CAMERA] Reader stopped")
    
    def get_frame(self) -> Optional[Tuple[cv2.Mat, float]]:
        """
        Get latest frame from queue or internal buffer.
        
        Returns:
            (frame, timestamp) or None if no frame available
        """
        # Try queue first
        try:
            frame, ts = self.frame_queue.get_nowait()
            with self.lock:
                self.latest_frame = (frame, ts)
            return frame, ts
        except queue.Empty:
            pass
        
        # Return cached frame if available
        with self.lock:
            if self.latest_frame is not None:
                return self.latest_frame
        
        return None
    
    def _reader_loop(self):
        """Main camera reader loop with reconnection logic."""
        cap = None
        reconnect_attempts = 0
        last_reconnect = time.time()
        
        while self.running:
            try:
                # Open camera if not connected
                if cap is None:
                    cap = cv2.VideoCapture(self.device_id if isinstance(self.device_id, int) 
                                          else str(self.device_id))
                    
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                    cap.set(cv2.CAP_PROP_FPS, self.fps)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    # Force minimum frame interval
                    cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
                    cap.set(cv2.CAP_PROP_SETTINGS, 0)
                    
                    if not cap.isOpened():
                        raise RuntimeError("Cannot open camera")
                    
                    self.connected = True
                    reconnect_attempts = 0
                    logger.info(f"[CAMERA] Connected to {self.device_id}")
                
                # Read frame with timing
                frame_start = time.perf_counter()
                ret, frame = cap.read()
                if not ret:
                    raise RuntimeError("Failed to read frame")
                
                # Queue frame
                timestamp = time.time()
                try:
                    self.frame_queue.put_nowait((frame, timestamp))
                    with self.lock:
                        self.latest_frame = (frame, timestamp)
                    self.frame_count += 1
                except queue.Full:
                    self.drop_count += 1
                
                # Frame delay - enforce strict timing
                elapsed = time.perf_counter() - frame_start
                sleep_time = max(0.001, self.frame_delay - elapsed)  # min 1ms
                time.sleep(sleep_time)
                
            except Exception as e:
                logger.error(f"[CAMERA] Error: {e}")
                
                if cap:
                    cap.release()
                    cap = None
                
                self.connected = False
                
                # Reconnection logic
                if reconnect_attempts < self.reconnect_max_attempts:
                    reconnect_attempts += 1
                    logger.info(f"[CAMERA] Reconnecting (attempt {reconnect_attempts}/{self.reconnect_max_attempts})...")
                    time.sleep(self.reconnect_timeout)
                else:
                    logger.error("[CAMERA] Max reconnection attempts reached, stopping")
                    self.running = False
        
        if cap:
            cap.release()
        logger.info("[CAMERA] Reader loop ended")
    
    def get_stats(self) -> dict:
        """Get camera statistics."""
        return {
            'frame_count': self.frame_count,
            'drop_count': self.drop_count,
            'connected': self.connected,
            'queue_size': self.frame_queue.qsize()
        }
