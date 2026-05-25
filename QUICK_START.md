# Quick Start Guide - Backend-Driven Face Attendance

## 🎯 Three Commands to Get Started

```bash
# Terminal 1
python app.py

# Terminal 2  
ngrok http 8000

# Terminal 3
# Copy ngrok URL and use in Flutter
```

---

## 📋 All Endpoints You Need

### Registration
```
1. POST /api/persons?name=John
   → Get person_id

2. POST /register
   → Store face image
```

### Attendance
```
3. Backend: POST /scan
   → Send face detection

4. Flutter: GET /poll
   → Get pending scans (every 10s)

5. Flutter: POST /ack
   → Confirm processing
```

### Status
```
GET /health → Server stats
GET /debug/pending → See queue
GET /debug/faces → See faces
GET /test_unknown → Test data
```

---

## 🔄 Simple Flow

```
Person Register:
  create_person() → person_id=1
  register_face(person_id=1, image)

Person Attendance:
  Backend detects face → POST /scan (member_id=1)
  Flutter polls GET /poll (every 10s)
  Flutter shows: "✅ Person 1 (92% confidence)"
  User confirms
  POST /ack scan_id → scan removed
```

---

## 💾 Database

Two new tables automatically created:

```
pending_scans
├─ id: UUID
├─ member_id: person ID
├─ timestamp: when detected
├─ confidence: match score
└─ image_base64: face image

registered_faces
├─ id: int
├─ member_id: person ID
├─ image_path: file location
└─ registered_at: enrollment time
```

---

## 🧪 Quick Test

```bash
# 1. Health
curl http://localhost:8000/health

# 2. Create person
curl -X POST "http://localhost:8000/api/persons?name=Test"

# 3. Send scan from backend
curl -X POST "http://localhost:8000/scan" \
  -H "Content-Type: application/json" \
  -d '{"member_id": 1, "confidence": 0.92}'

# 4. Flutter polls
curl http://localhost:8000/poll

# 5. Flutter acks
curl -X POST "http://localhost:8000/ack" \
  -H "Content-Type: application/json" \
  -d '{"scan_id": "..."}'
```

---

## 🎨 Response Format

### Scan Created
```json
{
  "success": true,
  "scan_id": "550e8400-...",
  "timestamp": 1716523845.123
}
```

### Poll Response
```json
{
  "success": true,
  "count": 2,
  "scans": [
    {
      "id": "550e8400-...",
      "member_id": 1,
      "timestamp": 1716523845.123,
      "recognized": true,
      "confidence": 0.92
    }
  ]
}
```

### Ack Response
```json
{
  "success": true,
  "scan_id": "550e8400-..."
}
```

---

## 🔌 Flutter Code (Minimal)

```dart
// 1. Register person
final res = await http.post(
  Uri.parse('$baseUrl/api/persons?name=John'),
);

// 2. Poll (in Timer loop, every 10 seconds)
final res = await http.get(Uri.parse('$baseUrl/poll'));
final data = jsonDecode(res.body);
for (var scan in data['scans']) {
  print('${scan['member_id']}: ${scan['confidence']}');
  
  // 3. Ack
  await http.post(Uri.parse('$baseUrl/ack'),
    body: jsonEncode({'scan_id': scan['id']}),
  );
}
```

---

## 📊 Status Checks

```bash
# Server health + stats
curl http://localhost:8000/health
→ {status: "ok", registered_persons: 5, pending_scans: 2}

# Debug queue
curl http://localhost:8000/debug/pending
→ {count: 2, scans: [...]}

# Debug faces
curl http://localhost:8000/debug/faces
→ {count: 5, faces: [...]}
```

---

## 🚀 Deployment (ngrok example)

```
Local:  http://localhost:8000
Tunnel: https://xxxx.ngrok-free.dev

Flutter baseUrl = 'https://xxxx.ngrok-free.dev'
```

---

## ⚡ Performance

- **Polling latency**: ~100-500ms
- **Scan processing**: <100ms
- **Database**: SQLite with WAL (concurrent writes supported)
- **Cleanup**: Auto-delete scans older than 1 hour

---

## 🎯 Done!

Everything is set up and ready to use. Just:

1. Start server: `python app.py`
2. Expose: `ngrok http 8000`
3. Update Flutter `baseUrl`
4. Test registration
5. Test attendance polling

**That's it!** 🎉
