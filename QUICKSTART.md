# Production Face Attendance System - Quick Start Guide

## 5-Minute Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Prepare Face Database
```bash
# Create directory structure
mkdir -p registered_faces/person1
mkdir -p registered_faces/person2

# Add face images (10-20 per person, diverse angles/lighting)
cp path/to/photos/john*.jpg registered_faces/person1/
```

**Image Requirements**:
- Format: JPG, PNG
- Clear frontal or slight angle faces
- Good lighting, no extreme blur
- Minimum 640x480 resolution
- Multiple angles/expressions per person

### 3. Configure System
```bash
# Edit config.yaml for your environment
vim config.yaml
```

**Key settings to check**:
```yaml
camera:
  device_id: 2              # Change to 0 for default webcam
  
server:
  url: https://your-server  # Your attendance endpoint
  
recognition:
  similarity_threshold: 0.35  # Adjust if getting false positives
```

### 4. Run System
```bash
python app.py
```

**Expected output**:
```
[SYSTEM] Initializing production face attendance system...
[DETECTOR] Initializing InsightFace (buffalo_l)...
[RECOGNIZER] Loading database from: ./registered_faces
[SUMMARY] Total: 45 | Loaded: 45 | People: 3
[SYSTEM] ✅ Initialization complete
[SYSTEM] Starting main loop...
```

**Press 'q' to quit**

---

## Common Configuration Changes

### Using USB Webcam Instead of Device 2
```yaml
camera:
  device_id: 0    # Default system camera
```

### Using IP Camera (RTSP)
```yaml
camera:
  device_id: 'rtsp://admin:password@192.168.1.100:554/stream'
```

### Faster Performance (Trade Accuracy)
```yaml
insightface:
  model_name: buffalo_m          # Faster than buffalo_l

performance:
  inference_every_n_frames: 6    # Skip more frames
  frame_scale: 0.25              # Smaller detection input
```

### Stricter Recognition (Fewer False Positives)
```yaml
recognition:
  similarity_threshold: 0.32      # Lower = stricter
  min_confident_frames: 8         # Wait longer for confirmation
```

### More Lenient Recognition (Fewer Misses)
```yaml
recognition:
  similarity_threshold: 0.40      # Higher = more permissive
  min_confident_frames: 3         # Accept faster
```

---

## Monitoring System Health

### Check Performance
```
Console shows:
- FPS: Current frames per second
- Detect/Track timings: Processing time
- Num faces: Active tracked faces
```

### Verify Recognitions
```
Look for logs:
✅ MATCH: john @ 0.32
📡 SCAN SENT: john
```

### Debug Issues
```
Turn on debug logging in console:
❌ NO MATCH @ 0.45
[QUALITY] ❌ blur=85.5 < 100.0
```

---

## Adding New People

1. **Create directory** (name must match attendance database):
```bash
mkdir registered_faces/jane_doe
```

2. **Add face images** (10-20 diverse photos):
```bash
cp jane_photos/*.jpg registered_faces/jane_doe/
```

3. **Wait 10 seconds** for automatic database reload
```
[DATABASE] Reloaded  # Appears in logs
```

4. **Test recognition** by showing camera
```
Expected: ✅ MATCH: jane_doe
```

---

## Troubleshooting

### System Won't Start
- Check Python version: `python --version` (need 3.9+)
- Install dependencies: `pip install -r requirements.txt`
- Check config.yaml syntax (YAML is whitespace-sensitive)

### Camera Not Working
- List cameras: `python -c "import cv2; cap=cv2.VideoCapture(0); print(cap.isOpened())"`
- For IP camera, test URL directly
- Check device_id in config

### False Positives (Wrong Matches)
- Lower `similarity_threshold` in config (e.g., 0.35 → 0.32)
- Add more training images (especially wrong people)
- Increase `min_confident_frames`

### False Negatives (Missing Matches)
- Raise `similarity_threshold` (e.g., 0.35 → 0.40)
- Add more diverse training images
- Check face quality (blur, angle, brightness)
- Relax quality filters

### Duplicate Scans
- Increase `per_person_cooldown` in attendance section
- Increase `duplicate_scan_window`

---

## Next Steps

1. **Read full documentation**: [REFACTORING_GUIDE.md](REFACTORING_GUIDE.md)
2. **Tune thresholds** based on false positive/negative rates
3. **Set up monitoring** for production
4. **Test with diverse users** and environments
5. **Calibrate database** with real attendance patterns

---

*For detailed configuration options, see config.yaml comments*
*For architecture details, see REFACTORING_GUIDE.md*
