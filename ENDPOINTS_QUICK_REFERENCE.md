# Quick Reference - Flutter API Endpoints

## All Endpoints You Need

### 1️⃣ REGISTRATION - Create Person
```
POST /api/persons?name=John%20Doe
Response: { "person_id": 1, "name": "John Doe", "success": true }
```

### 2️⃣ REGISTRATION - Enroll Face
```
POST /api/enrollment/manual
Form Data:
  - person_id: 1
  - name: John Doe
  - file: <image_file>

Response: { "person_id": 1, "name": "John Doe", "success": true }
```

### 3️⃣ ATTENDANCE - Recognize Face
```
POST /api/recognize
Form Data:
  - file: <image_file>

Response: {
  "success": true,
  "recognized": true,        // false if not recognized
  "person_id": 1,           // null if not recognized
  "name": "John Doe",       // null if not recognized
  "confidence": 0.92        // 0.0-1.0 score (>0.6 is good)
}
```

### 4️⃣ Verify Server is Working
```
GET /health
Response: { "status": "ok", "time": "..." }
```

---

## Flutter Implementation Pattern

```dart
// 1. REGISTRATION
final personResponse = await http.post(
  Uri.parse('http://192.168.1.X:8000/api/persons?name=John Doe'),
);
int personId = jsonDecode(personResponse.body)['person_id'];

// 2. ENROLL FACE
var enrollRequest = http.MultipartRequest('POST', 
  Uri.parse('http://192.168.1.X:8000/api/enrollment/manual'),
);
enrollRequest.fields['person_id'] = personId.toString();
enrollRequest.fields['name'] = 'John Doe';
enrollRequest.files.add(await http.MultipartFile.fromPath('file', imageFile.path));
await enrollRequest.send();

// 3. RECOGNIZE FACE
var recognizeRequest = http.MultipartRequest('POST', 
  Uri.parse('http://192.168.1.X:8000/api/recognize'),
);
recognizeRequest.files.add(await http.MultipartFile.fromPath('file', imageFile.path));
final response = await recognizeRequest.send();
final result = jsonDecode(await response.stream.bytesToString());

if (result['recognized']) {
  print('✅ ${result['name']} - Confidence: ${result['confidence']}');
} else {
  print('❌ Unknown person');
}
```

---

## Important Notes

✅ **Everything is already set up and working:**
- Database: SQLite (auto-created)
- Embeddings: InsightFace (512-dim vectors)
- Vector Search: FAISS (for fast lookup)
- API: FastAPI on port 8000

✅ **The flow:**
1. Create person → Get person_id
2. Upload face image → Extract embedding → Store in DB
3. Send face image → Extract embedding → Compare with stored → Get match

✅ **No extra steps needed** - just call these 3 endpoints from Flutter!

---

## Test Your Setup

```bash
# Terminal 1: Start server
cd c:\Users\Laptop Home\Documents\face_attendance
python app.py

# Terminal 2: Test endpoints
curl http://localhost:8000/health

# Or view interactive docs
# Open browser: http://localhost:8000/docs
```

---

## Server IP for Flutter

Find your PC IP:
```bash
# Windows
ipconfig

# Look for "IPv4 Address" (e.g., 192.168.1.100)
```

Then use in Flutter:
```dart
const String API_URL = 'http://192.168.1.100:8000';
```
