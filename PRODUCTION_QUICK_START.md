# PRODUCTION SETUP - Quick Reference

## ⚡ 5-Minute Production Setup

### 1. Install & Verify
```bash
pip install -r requirements.txt
python startup.py
```

### 2. Setup Faces Database
```bash
mkdir -p registered_faces/{person1,person2}
cp photos/person1/*.jpg registered_faces/person1/
cp photos/person2/*.jpg registered_faces/person2/
```

**Minimum:** 10+ photos per person, clear faces, good lighting

### 3. Configure for Your Setup
Edit `config.yaml`:
```yaml
camera:
  device_id: 0              # 0 = built-in, 1 = USB, or RTSP URL

server:
  url: https://your-api.com # Your attendance API
```

### 4. Run Production
```bash
python startup.py
```

---

## 🎯 Critical Thresholds for Recognition

| Setting | Default | Purpose |
|---------|---------|---------|
| `similarity_threshold` | 0.42 | Face match strictness (lower=stricter) |
| `min_confident_frames` | 2 | Frames needed before recognizing |
| `min_confidence_for_scan` | 0.50 | Confidence level before reporting |

### Tuning Guide
- **Too many false positives?** Lower `similarity_threshold` to 0.40
- **Not recognizing?** Raise it to 0.45
- **Slow recognition?** Lower `min_confident_frames` to 1

---

## 📊 Before Going Live - Checklist

- [ ] Python 3.8+ installed
- [ ] `pip install -r requirements.txt` completed
- [ ] `registered_faces/` has 2+ people with 10+ photos each
- [ ] Photos are clear, well-lit, diverse angles
- [ ] `python startup.py` passes all checks
- [ ] Camera works (`device_id` correct)
- [ ] Server URL configured and reachable
- [ ] First test run successful

---

## 🚀 Production Commands

```bash
# Verify system is ready
python startup.py

# Run production system
python startup.py

# Check database loaded
python -c "from core import FaceDetector, FaceRecognizer; r = FaceRecognizer('registered_faces', FaceDetector()); print(r.database.keys())"

# View logs
tail -f attendance.log
```

---

## ⚠️ Common Issues & Quick Fixes

| Issue | Solution |
|-------|----------|
| Camera not found | Change `device_id` in config.yaml (try 0, 1, 2) |
| Faces not recognized | Add more photos (10-15 per person), check photo quality |
| Wrong person recognized | Lower `similarity_threshold` to 0.40 or add training photos |
| Server errors | Verify URL is correct, check network, increase timeout |
| Slow performance | Lower camera resolution, set `inference_every_n_frames: 2` |

---

## 📁 Production Directory Structure

```
face_attendance/
├── startup.py              ← START HERE
├── config.yaml             ← Configure
├── requirements.txt
├── registered_faces/       ← Add face photos
│   ├── person1/
│   │   ├── photo1.jpg
│   │   └── ...
│   └── person2/
│       └── ...
├── app.py
├── server.py
├── core/
├── services/
├── models/
├── utils/
└── logs/
    └── attendance.log
```

---

## 🎓 Next Steps

1. **First Time?** Run `python startup.py` - it guides you
2. **Need Help?** See `DEPLOYMENT_GUIDE.md`
3. **Performance Issues?** Check `config.yaml` tuning section
4. **Debugging?** Enable DEBUG logging in config

---

## 💡 Pro Tips

✅ **For Best Results:**
- Add diverse photos: different angles, lighting, expressions
- Keep database updated
- Periodically retrain with new photos
- Monitor logs for patterns

✅ **For Speed:**
- Use lower camera resolution (480p instead of 1080p)
- Reduce FPS setting (20 instead of 30)
- Increase `inference_every_n_frames`

✅ **For Accuracy:**
- Increase `min_confident_frames` (3-5)
- Lower `similarity_threshold` (0.38-0.40)
- Add more training photos per person

---

## 📞 Support Checklist

If system doesn't work:
1. Run `python startup.py` - read all messages
2. Check logs: `tail -f attendance.log`
3. Verify database: `registered_faces/` has subdirectories with images
4. Test camera: Works in other apps?
5. Check config: All settings present and valid?

All checks passing? System is production-ready! 🎉
