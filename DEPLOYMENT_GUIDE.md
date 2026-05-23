# Production Face Attendance System - Deployment Guide

## Quick Start (Production-Ready)

### 1. System Requirements

**Hardware:**
- CPU: Intel i5/AMD Ryzen 5+ (or equivalent ARM processor)
- RAM: 4GB minimum (8GB recommended)
- Storage: 5GB minimum
- GPU: Optional (NVIDIA CUDA 11.8+ for GPU acceleration)
- Camera: USB or IP/RTSP camera

**OS Support:**
- ✅ Linux (Ubuntu 20.04+)
- ✅ Windows 10/11
- ✅ macOS 11+

### 2. Installation

#### Step 1: Clone/Download Project
```bash
cd face_attendance
```

#### Step 2: Create Python Virtual Environment
```bash
# Linux/macOS
python3 -m venv venv
source venv/bin/activate

# Windows (PowerShell)
python -m venv venv
.\venv\Scripts\Activate.ps1
```

#### Step 3: Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**For GPU Support (Optional):**
```bash
pip install onnxruntime-gpu  # Requires NVIDIA CUDA 11.8+
```

### 3. Setup Face Database

#### Create Directory Structure
```bash
mkdir -p registered_faces/person1
mkdir -p registered_faces/person2
mkdir -p registered_faces/person3
```

#### Add Face Images
For each person, add 10-20 high-quality photos:
```bash
cp /path/to/photos/person1/*.jpg registered_faces/person1/
cp /path/to/photos/person2/*.jpg registered_faces/person2/
```

**Image Quality Requirements:**
- ✅ Clear, well-lit faces (no extreme shadows)
- ✅ Multiple angles: frontal, 30° left, 30° right
- ✅ Multiple expressions: neutral, slight smile, serious
- ✅ No heavy occlusion (glasses OK, masks NO)
- ✅ Resolution: 640x480 minimum
- ✅ Format: JPG, PNG

**Database Structure:**
```
registered_faces/
├── john/
│   ├── john_frontal_1.jpg
│   ├── john_left_30.jpg
│   ├── john_right_30.jpg
│   └── john_smile.jpg
├── jane/
│   ├── jane_frontal_1.jpg
│   └── ...
└── bob/
    └── ...
```

### 4. Configure System

Edit `config.yaml` for your environment:

```yaml
# 📷 Camera Settings
camera:
  device_id: 0                    # 0=built-in, 1+=USB, or IP URL
  width: 640
  height: 480
  fps: 30

# 🎯 Recognition Thresholds (Production-Optimized)
recognition:
  similarity_threshold: 0.42      # Lower = stricter (0.40-0.45 recommended)
  min_confident_frames: 2         # Frames needed to confirm
  
# 🖥️  Server Configuration
server:
  url: https://your-attendance-server.com
  endpoint: /scan
  timeout: 20
  max_retries: 3

# ✋ Attendance Settings
attendance:
  per_person_cooldown: 8.0        # Seconds before re-scanning same person
  min_confidence_for_scan: 0.50   # Confidence needed for acceptance
```

### 5. Pre-Flight Checks

Run the health check system before first launch:

```bash
python startup.py
```

This checks:
- ✅ Python version (3.8+)
- ✅ All dependencies installed
- ✅ Configuration validity
- ✅ Database integrity
- ✅ Camera accessibility
- ✅ Disk space availability
- ✅ Network connectivity

### 6. Launch Production System

```bash
python startup.py
```

This will:
1. Run comprehensive health checks
2. Validate configuration
3. Load face database
4. Initialize camera
5. Start the main system

**First Run Output:**
```
[SYSTEM] Initializing production face attendance system...
[DETECTOR] Initializing InsightFace (buffalo_l)...
[DETECTOR] ✅ Ready (providers: ['CUDAExecutionProvider', 'CPUExecutionProvider'])
[RECOGNIZER] Loading database from: /path/to/registered_faces
[RECOGNIZER] Loading database...
[OK] john: john_1.jpg
[OK] john: john_2.jpg
[SUMMARY] Total: 20 | Loaded: 20 | People: 2
```

Press `Ctrl+C` to exit.

---

## Troubleshooting

### Issue: Camera Not Opening
**Error:** `Can't open device 2`

**Solution:**
1. Check available cameras:
   - Windows: Device Manager → Cameras
   - Linux: `ls -l /dev/video*`
   - macOS: `system_profiler SPCameraDataType`

2. Update `config.yaml`:
   ```yaml
   camera:
     device_id: 0  # Try 0, 1, 2 in order
   ```

### Issue: Faces Not Being Recognized
**Error:** No names showing in video feed

**Cause:** Recognition threshold too strict or database empty

**Solutions:**
1. Verify database:
   ```bash
   python -c "
   from core import FaceDetector
   from core import FaceRecognizer
   
   detector = FaceDetector()
   recognizer = FaceRecognizer('registered_faces', detector)
   print(f'Loaded: {len(recognizer.database)} people')
   print(f'Database: {list(recognizer.database.keys())}')
   "
   ```

2. Loosen recognition threshold in `config.yaml`:
   ```yaml
   recognition:
     similarity_threshold: 0.45  # More lenient
   ```

3. Add more face images (at least 10-15 per person)

4. Check image quality - ensure clear, well-lit faces

### Issue: False Positives (Wrong Person Recognized)
**Cause:** Recognition threshold too lenient

**Solution:**
Tighten threshold in `config.yaml`:
```yaml
recognition:
  similarity_threshold: 0.40  # Stricter
```

Or add more training images for difficult individuals.

### Issue: Server Connection Failures
**Error:** `HTTPError: Connection refused`

**Solutions:**
1. Verify server is running:
   ```bash
   curl -v https://your-server/health
   ```

2. Check firewall rules

3. Update server URL in `config.yaml`:
   ```yaml
   server:
     url: https://correct-url.com
     timeout: 30  # Increase if server is slow
   ```

4. Enable retry logic:
   ```yaml
   server:
     max_retries: 5
     retry_backoff: exponential
   ```

### Issue: High CPU/GPU Usage
**Solution:**
Reduce inference frequency:
```yaml
performance:
  inference_every_n_frames: 2  # Process every 2nd frame instead of 1st
```

### Issue: Liveness Detection Failing
**Cause:** LivenessDetector model not found or threshold too strict

**Solution:**
```yaml
liveness:
  enabled: false  # Disable if not needed for your use case
  # or
  threshold: 0.60  # Make more lenient
```

---

## Performance Tuning

### For Better Accuracy
```yaml
recognition:
  similarity_threshold: 0.40      # Stricter matching
  min_confident_frames: 3         # Require more frames
  
quality:
  blur_threshold: 80.0            # Stricter blur filter
  max_yaw: 35                     # Stricter pose filter
```

### For Better Speed
```yaml
camera:
  width: 480                      # Lower resolution
  fps: 15                         # Reduce FPS
  
performance:
  inference_every_n_frames: 2     # Process fewer frames
  frame_scale: 0.3                # Downscale for detection
  
insightface:
  det_size: [256, 256]            # Smaller detector input
```

### For Balanced Performance (Recommended)
```yaml
camera:
  width: 640
  height: 480
  fps: 30
  
recognition:
  similarity_threshold: 0.42       # Balanced threshold
  min_confident_frames: 2
  
performance:
  inference_every_n_frames: 1     # Every frame
  frame_scale: 0.5                # Moderate downscaling
```

---

## Monitoring and Logging

### Enable Debug Logging
In `config.yaml`:
```yaml
logging:
  level: DEBUG
  log_file: attendance_debug.log
```

Check logs:
```bash
tail -f attendance.log          # Real-time logging
grep "ERROR" attendance.log     # Find errors
grep "Recognition" attendance.log  # Find recognitions
```

### Performance Metrics
View in-app metrics:
- **FPS**: Frames per second (detection + display)
- **Detection Time**: How long face detection takes
- **Recognition Time**: How long matching takes
- **Track Count**: Number of active tracked faces

---

## Advanced Configuration

### Custom Thresholds for Different Scenarios

**High-Security Scenario (Low False Positives):**
```yaml
recognition:
  similarity_threshold: 0.35       # Very strict
  min_confident_frames: 5          # Need 5 frames
  
quality:
  blur_threshold: 80.0
  max_yaw: 30
  min_face_size: 100
```

**High-Throughput Scenario (Low Latency):**
```yaml
recognition:
  similarity_threshold: 0.48       # Lenient
  min_confident_frames: 1          # Quick acceptance
  
quality:
  blur_threshold: 120.0
  max_yaw: 60
  
performance:
  inference_every_n_frames: 2
```

**Mobile/Edge Device Scenario:**
```yaml
camera:
  width: 320
  height: 240
  fps: 15

performance:
  inference_every_n_frames: 3
  frame_scale: 0.3
  
insightface:
  model_name: buffalo_s           # Smaller model
  det_size: [256, 256]
```

---

## Database Management

### Hot Reload Database
Add new people without restarting:
```python
from core import FaceRecognizer
recognizer = FaceRecognizer("registered_faces")
recognizer.reload_database()  # Reload after adding images
```

### Export Recognition Results
```bash
grep "SCAN:" attendance.log > attendance_records.txt
```

### Backup Database
```bash
tar -czf registered_faces_backup.tar.gz registered_faces/
```

---

## Deployment Checklist

- [ ] Python 3.8+ installed
- [ ] All dependencies from requirements.txt
- [ ] registered_faces/ directory with 2+ people
- [ ] 10+ quality images per person
- [ ] config.yaml configured for your environment
- [ ] Camera tested and working
- [ ] Server endpoint verified (if using HTTP)
- [ ] Startup checks pass (`python startup.py`)
- [ ] First run test completed successfully
- [ ] Logging configured appropriately
- [ ] Performance meets requirements

---

## Getting Help

**Enable Debug Mode:**
```yaml
logging:
  level: DEBUG
```

**Check System Health:**
```bash
python startup.py
```

**Verify Database Loads:**
```bash
python -c "
from core import FaceDetector, FaceRecognizer
detector = FaceDetector()
recognizer = FaceRecognizer('registered_faces', detector)
print(recognizer.database_embeddings.keys())
"
```

**Test Recognition:**
```bash
python -c "
import cv2
import numpy as np
from core import FaceDetector, FaceRecognizer

detector = FaceDetector()
recognizer = FaceRecognizer('registered_faces', detector)

# Test with first image
img = cv2.imread('registered_faces/person1/test.jpg')
detections, _ = detector.detect(img)
if detections:
    embedding = detections[0]['embedding']
    name, distance, scores = recognizer.identify(embedding, 0.42)
    print(f'Result: {name} (distance: {distance:.3f})')
    print(f'All scores: {scores}')
"
```

---

## Version Information

- **System**: Production Face Attendance v2.0
- **Face Recognition**: InsightFace (ArcFace embeddings)
- **Tracking**: ByteTrack
- **Python**: 3.8+
- **OpenCV**: 4.8.0+
- **InsightFace**: 0.7.3+

Last Updated: 2024
