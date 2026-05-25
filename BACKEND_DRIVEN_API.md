# Backend-Driven Face Attendance API

## Architecture Overview

```
┌─────────────────────┐
│  Backend Camera     │  Runs face detection
│  (Python Server)    │
└──────────┬──────────┘
           │ 1. POST /scan
           │    (member_id, image, confidence)
           ▼
┌─────────────────────┐
│  Pending Scans DB   │  Queue of detection events
│  SQLite             │
└──────────┬──────────┘
           │ 2. GET /poll
           │    (Flutter polls periodically)
           ▼
┌─────────────────────┐
│  Flutter App        │  Shows results to user
│  (Mobile Client)    │
└──────────┬──────────┘
           │ 3. POST /ack
           │    (confirm processing)
           ▼
┌─────────────────────┐
│  Scan Removed       │  Frontend acknowledged
│  from Queue         │
└─────────────────────┘
```

## Flow

1. **Backend Camera detects face** → Extracts embedding → Calls `POST /scan`
2. **Flutter polls** → Calls `GET /poll` (every 10 seconds)
3. **Flutter gets scan result** → Shows to user (recognized or unknown)
4. **Flutter acknowledges** → Calls `POST /ack` → Scan removed from queue

---

## API Endpoints

### 1. POST /scan - Backend sends scan event

**Called by:** Backend camera system (Python)  
**Purpose:** Store a detected face scan in the pending queue

**Request:**
```json
{
  "member_id": 1,           // Person ID if recognized, null if unknown
  "image_base64": "...",    // Optional: base64 encoded face image
  "confidence": 0.92,       // Optional: recognition confidence (0-1)
  "face_quality": "good"    // Optional: quality assessment
}
```

**Response:**
```json
{
  "success": true,
  "scan_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": 1716523845.123
}
```

**cURL:**
```bash
curl -X POST "http://localhost:8000/scan" \
  -H "Content-Type: application/json" \
  -d '{
    "member_id": 1,
    "image_base64": "...",
    "confidence": 0.92
  }'
```

**Python:**
```python
import requests
import base64

image_b64 = base64.b64encode(image_bytes).decode()

response = requests.post(
    "http://localhost:8000/scan",
    json={
        "member_id": 1,
        "image_base64": image_b64,
        "confidence": 0.92,
        "face_quality": "good"
    }
)
```

---

### 2. GET /poll - Flutter polls for scans

**Called by:** Flutter app (periodically)  
**Purpose:** Get list of pending scans to display to user

**Parameters:**
- `last_timestamp` (float, optional): Only get scans after this timestamp
- `last_id` (string, optional): Resolve timestamp from scan ID

**Response:**
```json
{
  "success": true,
  "count": 2,
  "scans": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "member_id": 1,
      "timestamp": 1716523845.123,
      "image_base64": "...",
      "recognized": true,
      "confidence": 0.92,
      "face_quality": "good"
    },
    {
      "id": "660e8400-e29b-41d4-a716-446655440111",
      "member_id": null,        // Unknown person
      "timestamp": 1716523850.456,
      "image_base64": "...",
      "recognized": false,
      "confidence": null,
      "face_quality": null
    }
  ]
}
```

**cURL:**
```bash
# Get all pending scans
curl -X GET "http://localhost:8000/poll"

# Get scans after specific timestamp
curl -X GET "http://localhost:8000/poll?last_timestamp=1716523845"

# Resolve timestamp from scan ID
curl -X GET "http://localhost:8000/poll?last_id=550e8400-e29b-41d4-a716-446655440000"
```

**Flutter:**
```dart
Future<List<Map<String, dynamic>>> pollScans({double? lastTimestamp}) async {
  final uri = lastTimestamp == null
      ? Uri.parse('http://localhost:8000/poll')
      : Uri.parse('http://localhost:8000/poll?last_timestamp=$lastTimestamp');

  final response = await http.get(uri).timeout(Duration(seconds: 15));
  
  if (response.statusCode == 200) {
    final data = jsonDecode(response.body);
    return List<Map<String, dynamic>>.from(data['scans'] ?? []);
  }
  throw Exception('Poll failed');
}

// Usage
final scans = await pollScans();
for (var scan in scans) {
  if (scan['recognized']) {
    print('✅ ${scan['member_id']} recognized with confidence ${scan['confidence']}');
  } else {
    print('❌ Unknown person detected');
  }
}
```

---

### 3. POST /ack - Flutter acknowledges scan

**Called by:** Flutter app (after processing)  
**Purpose:** Remove scan from pending queue

**Request:**
```json
{
  "scan_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Response:**
```json
{
  "success": true,
  "scan_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**cURL:**
```bash
curl -X POST "http://localhost:8000/ack" \
  -H "Content-Type: application/json" \
  -d '{"scan_id": "550e8400-e29b-41d4-a716-446655440000"}'
```

**Flutter:**
```dart
Future<void> acknowledgeScan(String scanId) async {
  try {
    await http.post(
      Uri.parse('http://localhost:8000/ack'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'scan_id': scanId}),
    ).timeout(Duration(seconds: 5));
  } catch (e) {
    print('ACK failed: $e');
  }
}

// Usage
await acknowledgeScan(scan['id']);
```

---

### 4. POST /register - Register face for member

**Called by:** Backend enrollment system  
**Purpose:** Store face for a person (member_id)

**Request (multipart form-data or JSON):**
```
member_id: 1
image_base64: "..." OR file upload
```

**Response:**
```json
{
  "success": true,
  "member_id": 1,
  "image_path": "registered_faces/1.jpg"
}
```

**cURL:**
```bash
# With base64
curl -X POST "http://localhost:8000/register" \
  -H "Content-Type: application/json" \
  -d '{
    "member_id": 1,
    "image_base64": "..."
  }'

# With file upload
curl -X POST "http://localhost:8000/register" \
  -F "member_id=1" \
  -F "file=@face.jpg"
```

---

### 5. GET /health - Check server status

**Called by:** Flutter or admin dashboard  
**Purpose:** Verify server is running and get stats

**Response:**
```json
{
  "status": "ok",
  "time": "2026-05-25T10:30:45.123456",
  "registered_persons": 5,
  "pending_scans": 2,
  "registered_faces": 5
}
```

**cURL:**
```bash
curl -X GET "http://localhost:8000/health"
```

---

## Complete Flutter Polling Example

```dart
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'dart:async';

class FaceAttendanceService {
  final String baseUrl = 'http://192.168.1.100:8000';
  Timer? _pollTimer;
  double? _lastTimestamp;

  /// Start polling for scans
  void startPolling({
    required Future<void> Function(ScanEvent scan) onNewScan,
    required void Function(String error) onError,
    Duration interval = const Duration(seconds: 10),
  }) {
    _pollTimer = Timer.periodic(interval, (_) async {
      try {
        final uri = _lastTimestamp == null
            ? Uri.parse('$baseUrl/poll')
            : Uri.parse('$baseUrl/poll?last_timestamp=$_lastTimestamp');

        final response = await http.get(uri).timeout(Duration(seconds: 15));
        
        if (response.statusCode != 200) return;

        final data = jsonDecode(response.body) as Map<String, dynamic>;
        final scans = (data['scans'] ?? []) as List;

        for (final scanJson in scans) {
          final scan = ScanEvent.fromJson(scanJson);
          
          try {
            await onNewScan(scan);
            
            // Update timestamp
            if (scan.timestamp != null &&
                (_lastTimestamp == null || scan.timestamp! > _lastTimestamp!)) {
              _lastTimestamp = scan.timestamp;
            }
          } catch (e) {
            debugPrint('Error processing scan: $e');
          }
        }
      } catch (e) {
        onError(e.toString());
      }
    });
  }

  /// Acknowledge a scan
  Future<void> ackScan(String scanId) async {
    try {
      await http.post(
        Uri.parse('$baseUrl/ack'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'scan_id': scanId}),
      ).timeout(Duration(seconds: 5));
    } catch (e) {
      debugPrint('ACK failed: $e');
    }
  }

  void stopPolling() {
    _pollTimer?.cancel();
  }
}

// Data model
class ScanEvent {
  final String scanId;
  final int? memberId;
  final bool recognized;
  final double? confidence;
  final String? faceQuality;
  final String? imageBase64;
  final double? timestamp;

  ScanEvent({
    required this.scanId,
    this.memberId,
    this.recognized = false,
    this.confidence,
    this.faceQuality,
    this.imageBase64,
    this.timestamp,
  });

  factory ScanEvent.fromJson(Map<String, dynamic> json) {
    return ScanEvent(
      scanId: json['id'],
      memberId: json['member_id'],
      recognized: json['recognized'] == true,
      confidence: (json['confidence'] as num?)?.toDouble(),
      faceQuality: json['face_quality'],
      imageBase64: json['image_base64'],
      timestamp: (json['timestamp'] as num?)?.toDouble(),
    );
  }
}

// Usage in Widget
class AttendanceScreen extends StatefulWidget {
  @override
  State<AttendanceScreen> createState() => _AttendanceScreenState();
}

class _AttendanceScreenState extends State<AttendanceScreen> {
  final service = FaceAttendanceService();
  List<ScanEvent> scans = [];

  @override
  void initState() {
    super.initState();
    service.startPolling(
      onNewScan: (scan) async {
        setState(() => scans.add(scan));
        
        if (scan.recognized) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('✅ Member ${scan.memberId} recognized')),
          );
        } else {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('❌ Unknown person detected')),
          );
        }
        
        // Acknowledge after 2 seconds
        await Future.delayed(Duration(seconds: 2));
        await service.ackScan(scan.scanId);
      },
      onError: (error) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error: $error')),
        );
      },
    );
  }

  @override
  void dispose() {
    service.stopPolling();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Attendance')),
      body: ListView.builder(
        itemCount: scans.length,
        itemBuilder: (context, index) {
          final scan = scans[index];
          return ListTile(
            title: Text(
              scan.recognized ? 'Member ${scan.memberId}' : 'Unknown',
            ),
            subtitle: Text(
              'Confidence: ${(scan.confidence ?? 0).toStringAsFixed(2)}',
            ),
            leading: Icon(
              scan.recognized ? Icons.check_circle : Icons.help_outline,
              color: scan.recognized ? Colors.green : Colors.orange,
            ),
          );
        },
      ),
    );
  }
}
```

---

## Debug Endpoints (Development)

```bash
# See all pending scans
curl http://localhost:8000/debug/pending

# See all registered faces
curl http://localhost:8000/debug/faces

# Add test unknown scan
curl http://localhost:8000/test_unknown
```

---

## Key Differences from Direct API

| Aspect | Backend-Driven | Direct API |
|--------|---|---|
| Who captures image | Backend camera | Flutter app |
| Who detects faces | Backend | Backend |
| Flutter role | Polls & displays | Sends images |
| Queue system | `/scan` → `/poll` → `/ack` | Direct `/recognize` |
| Latency | ~100-500ms polling | Immediate |
| Use case | Fixed camera, many clients | Mobile app with camera |

---

## Environment Setup

```bash
# Start server
python app.py

# Server will run on http://0.0.0.0:8000
# Use http://192.168.1.X:8000 for Flutter (replace X with your PC IP)

# View docs
http://localhost:8000/docs
```
