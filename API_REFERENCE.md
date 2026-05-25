# Complete API Reference - All Endpoints

## Quick Start

```bash
# Terminal 1: Start server
python app.py
# Server: http://localhost:8000

# Terminal 2: Expose with ngrok
ngrok http 8000
# Public URL: https://xxxx-xxxx-xxxx.ngrok-free.dev

# Terminal 3: Update Flutter baseUrl
const String baseUrl = 'https://xxxx-xxxx-xxxx.ngrok-free.dev';
```

---

## All Endpoints (Grouped by Function)

### 🟢 Health & Status

#### GET /health
Check server health and get statistics.

**Request:**
```bash
GET /health
```

**Response (200):**
```json
{
  "status": "ok",
  "time": "2026-05-25T10:30:45.123456",
  "registered_persons": 5,
  "pending_scans": 2,
  "registered_faces": 5
}
```

---

### 🟡 Person Management

#### POST /api/persons
Create a new person for registration.

**Request:**
```bash
POST /api/persons?name=John%20Doe
```

**Response (200):**
```json
{
  "success": true,
  "person_id": 1,
  "name": "John Doe"
}
```

---

#### GET /api/persons
Get all registered persons.

**Request:**
```bash
GET /api/persons
```

**Response (200):**
```json
{
  "success": true,
  "count": 2,
  "persons": [
    {
      "person_id": 1,
      "name": "John Doe",
      "employee_id": null,
      "is_active": true,
      "created_at": "2026-05-25T10:00:00"
    }
  ]
}
```

---

### 🔵 Face Enrollment

#### POST /api/enrollment/manual
Upload a face image for embedding extraction (direct method).

**Request (multipart form-data):**
```
person_id: 1
name: John Doe
file: <image_file>
```

**Response (200):**
```json
{
  "success": true,
  "person_id": 1,
  "name": "John Doe",
  "message": "Face enrolled successfully"
}
```

---

#### POST /register
Register face for member (backend-driven method).

**Request (JSON):**
```json
{
  "member_id": 1,
  "image_base64": "..."
}
```

**Response (200):**
```json
{
  "success": true,
  "member_id": 1,
  "image_path": "registered_faces/1.jpg"
}
```

---

### 🟣 Recognition

#### POST /api/recognize
Recognize a face from an image (direct method).

**Request (multipart form-data):**
```
file: <image_file>
```

**Response (200 - recognized):**
```json
{
  "success": true,
  "recognized": true,
  "person_id": 1,
  "name": "John Doe",
  "confidence": 0.92,
  "best_score": 0.92,
  "all_scores": {
    "1": 0.92,
    "2": 0.45
  }
}
```

**Response (200 - not recognized):**
```json
{
  "success": true,
  "recognized": false,
  "person_id": null,
  "name": null,
  "confidence": 0.0,
  "best_score": 0.55,
  "all_scores": {
    "1": 0.55,
    "2": 0.42
  }
}
```

**Response (400 - no face):**
```json
{
  "success": false,
  "recognized": false,
  "person_id": null,
  "name": null,
  "confidence": 0.0,
  "message": "No face detected in image"
}
```

---

### 📋 Backend-Driven Polling

#### POST /scan
Backend camera sends a scan event.

**Request (JSON):**
```json
{
  "member_id": 1,
  "image_base64": "...",
  "confidence": 0.92,
  "face_quality": "good"
}
```

**Response (200):**
```json
{
  "success": true,
  "scan_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": 1716523845.123
}
```

---

#### GET /poll
Flutter polls for pending scans from backend camera.

**Request:**
```bash
GET /poll
GET /poll?last_timestamp=1716523845
GET /poll?last_id=550e8400-e29b-41d4-a716-446655440000
```

**Response (200):**
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
      "member_id": null,
      "timestamp": 1716523850.456,
      "recognized": false
    }
  ]
}
```

---

#### POST /ack
Flutter acknowledges a scan (removes from queue).

**Request (JSON):**
```json
{
  "scan_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Response (200):**
```json
{
  "success": true,
  "scan_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

### 🛠️ Debug Endpoints (Development Only)

#### GET /debug/pending
Show all pending scans in the queue.

#### GET /debug/faces
Show all registered faces.

#### GET /test_unknown
Add a test unknown scan for debugging.

---

## Error Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad Request |
| 500 | Server Error |

---

## Authentication

Currently: No authentication (open API)

---

## Testing with ngrok

```bash
# Terminal 1: Start server
python app.py

# Terminal 2: Expose with ngrok
ngrok http 8000

# Terminal 3: Test
export URL="https://xxxx.ngrok-free.dev"
curl $URL/health
curl -X POST "$URL/api/persons?name=Test"
curl -X POST "$URL/api/recognize" -F "file=@face.jpg"
```
  },
  "uptime_seconds": 3600
}
```

---

## Person Management

### Create Person
```http
POST /api/persons
Content-Type: application/json

{
  "name": "John Doe",
  "employee_id": "EMP001",
  "department": "Engineering"
}
```

**Response (201)**:
```json
{
  "id": 1,
  "name": "John Doe",
  "employee_id": "EMP001",
  "department": "Engineering",
  "created_at": "2024-01-01T10:00:00Z"
}
```

**Errors**:
- `400`: Invalid data
- `409`: Employee ID already exists

### List All Persons
```http
GET /api/persons
```

**Query Parameters**:
- `skip`: Offset (default 0)
- `limit`: Max results (default 100)
- `search`: Filter by name

**Response (200)**:
```json
[
  {
    "id": 1,
    "name": "John Doe",
    "employee_id": "EMP001",
    "created_at": "2024-01-01T10:00:00Z"
  },
  {
    "id": 2,
    "name": "Jane Smith",
    "employee_id": "EMP002",
    "created_at": "2024-01-01T10:05:00Z"
  }
]
```

### Get Person Details
```http
GET /api/persons/{person_id}
```

**Response (200)**:
```json
{
  "id": 1,
  "name": "John Doe",
  "employee_id": "EMP001",
  "created_at": "2024-01-01T10:00:00Z",
  "embeddings_count": 5,
  "last_attendance": "2024-01-15T09:30:00Z"
}
```

**Errors**:
- `404`: Person not found

### Update Person
```http
PUT /api/persons/{person_id}
Content-Type: application/json

{
  "name": "John Smith",
  "department": "Management"
}
```

**Response (200)**:
```json
{
  "id": 1,
  "name": "John Smith",
  "employee_id": "EMP001",
  "department": "Management",
  "updated_at": "2024-01-15T12:00:00Z"
}
```

### Delete Person
```http
DELETE /api/persons/{person_id}
```

**Response (204)**: No content

**Note**: Deletes person and all related data

---

## Attendance Recording

### Record Check-In
```http
POST /api/attendance/checkin
Content-Type: application/json

{
  "person_id": 1,
  "confidence": 0.95,
  "notes": "Face recognized"
}
```

**Response (201)**:
```json
{
  "id": 1001,
  "person_id": 1,
  "check_in": "2024-01-15T09:30:00Z",
  "confidence_in": 0.95
}
```

**Errors**:
- `404`: Person not found
- `409`: Duplicate check-in (within cooldown)

### Record Check-Out
```http
POST /api/attendance/checkout
Content-Type: application/json

{
  "record_id": 1001,
  "confidence": 0.92
}
```

**Response (200)**:
```json
{
  "id": 1001,
  "person_id": 1,
  "check_in": "2024-01-15T09:30:00Z",
  "check_out": "2024-01-15T17:45:00Z",
  "duration_minutes": 495,
  "confidence_in": 0.95,
  "confidence_out": 0.92
}
```

### Get Today's Attendance
```http
GET /api/attendance/today
```

**Query Parameters**:
- `person_id`: Filter by person (optional)
- `skip`: Offset (default 0)
- `limit`: Max results (default 100)

**Response (200)**:
```json
[
  {
    "id": 1001,
    "person_id": 1,
    "name": "John Doe",
    "check_in": "2024-01-15T09:30:00Z",
    "check_out": "2024-01-15T17:45:00Z",
    "confidence_in": 0.95,
    "confidence_out": 0.92
  }
]
```

### Get Attendance Range
```http
GET /api/attendance/range
```

**Query Parameters**:
- `start_date`: ISO format (required)
- `end_date`: ISO format (required)
- `person_id`: Filter by person (optional)
- `skip`: Offset (default 0)
- `limit`: Max results (default 1000)

**Example**:
```
/api/attendance/range?start_date=2024-01-01&end_date=2024-01-31
```

**Response (200)**:
```json
[
  {
    "id": 1001,
    "person_id": 1,
    "name": "John Doe",
    "check_in": "2024-01-15T09:30:00Z",
    "check_out": "2024-01-15T17:45:00Z",
    "date": "2024-01-15"
  }
]
```

### Get Person Status Today
```http
GET /api/attendance/status/{person_id}
```

**Response (200)**:
```json
{
  "person_id": 1,
  "name": "John Doe",
  "status": "checked_in",
  "check_in": "2024-01-15T09:30:00Z",
  "minutes_present": 480,
  "confidence": 0.95
}
```

**Status Values**: `not_present`, `checked_in`, `checked_out`

---

## Unknown Candidates

### List Unknown Candidates
```http
GET /api/candidates
```

**Query Parameters**:
- `skip`: Offset (default 0)
- `limit`: Max results (default 50)

**Response (200)**:
```json
[
  {
    "id": 1,
    "track_count": 15,
    "confidence": 0.82,
    "seen_dates": ["2024-01-10", "2024-01-11", "2024-01-12"],
    "created_at": "2024-01-10T10:00:00Z",
    "ready_for_enrollment": true
  }
]
```

### Get Candidate Details
```http
GET /api/candidates/{candidate_id}
```

**Response (200)**:
```json
{
  "id": 1,
  "track_count": 15,
  "confidence": 0.82,
  "best_face_image": "base64_encoded_image",
  "seen_dates": ["2024-01-10", "2024-01-11"],
  "average_embedding": [0.1, 0.2, ...],
  "ready_for_enrollment": true
}
```

### Ignore Candidate
```http
POST /api/candidates/{candidate_id}/ignore
Content-Type: application/json

{
  "reason": "False positive - not a real person",
  "days_to_expiry": 30
}
```

**Response (200)**:
```json
{
  "id": 1,
  "status": "ignored",
  "reason": "False positive - not a real person",
  "expiry_date": "2024-02-14T12:00:00Z"
}
```

### Convert Candidate to Person
```http
POST /api/candidates/{candidate_id}/convert
Content-Type: application/json

{
  "name": "Unknown Person",
  "employee_id": "UNK001",
  "department": "Unknown"
}
```

**Response (201)**:
```json
{
  "person_id": 150,
  "name": "Unknown Person",
  "employee_id": "UNK001",
  "embeddings_count": 15,
  "confidence": 0.82,
  "created_from_candidate": 1
}
```

### Get Candidates Ready for Enrollment
```http
GET /api/candidates/ready
```

**Response (200)**:
```json
[
  {
    "id": 1,
    "track_count": 15,
    "confidence": 0.82,
    "ready_score": 0.88
  }
]
```

---

## System Statistics

### Get System Stats
```http
GET /api/stats
```

**Response (200)**:
```json
{
  "summary": {
    "total_persons": 150,
    "total_embeddings": 450,
    "total_attendance_records": 5000,
    "unknown_candidates": 23,
    "ignored_candidates": 5
  },
  "today": {
    "check_ins": 142,
    "check_outs": 135,
    "unique_persons": 142,
    "average_confidence": 0.92
  },
  "performance": {
    "detection_avg_ms": 45,
    "recognition_avg_ms": 8,
    "total_inference_avg_ms": 65,
    "faiss_search_avg_ms": 2
  },
  "uptime_hours": 48,
  "database_size_mb": 125
}
```

### Get Attendance Report
```http
GET /api/attendance/report
```

**Query Parameters**:
- `start_date`: ISO format (required)
- `end_date`: ISO format (required)
- `group_by`: `day`, `week`, `month` (default: day)

**Response (200)**:
```json
{
  "period": "2024-01-01 to 2024-01-31",
  "total_records": 3500,
  "by_date": [
    {
      "date": "2024-01-01",
      "check_ins": 142,
      "check_outs": 135,
      "avg_confidence": 0.91
    }
  ],
  "summary": {
    "total_person_days": 3500,
    "avg_check_in_time": "09:15",
    "avg_check_out_time": "17:30"
  }
}
```

---

## Embeddings Management

### Get Person Embeddings
```http
GET /api/persons/{person_id}/embeddings
```

**Response (200)**:
```json
[
  {
    "id": 1,
    "confidence": 0.95,
    "source": "enrollment",
    "created_at": "2024-01-15T10:00:00Z"
  },
  {
    "id": 2,
    "confidence": 0.92,
    "source": "enrollment",
    "created_at": "2024-01-15T10:05:00Z"
  }
]
```

### Add Embedding to Person
```http
POST /api/persons/{person_id}/embeddings
Content-Type: application/json

{
  "embedding": [0.1, 0.2, ...],  // 512-dim vector
  "confidence": 0.95,
  "source": "manual_enrollment"
}
```

**Response (201)**:
```json
{
  "id": 5,
  "person_id": 1,
  "confidence": 0.95,
  "created_at": "2024-01-15T14:00:00Z"
}
```

### Get Average Embedding
```http
GET /api/persons/{person_id}/embedding/average
```

**Response (200)**:
```json
{
  "embedding": [0.12, 0.18, ...],
  "source_count": 5,
  "confidence": 0.93
}
```

---

## Error Responses

### 400 Bad Request
```json
{
  "detail": "Invalid input: employee_id required"
}
```

### 401 Unauthorized
```json
{
  "detail": "Authentication required"
}
```

### 403 Forbidden
```json
{
  "detail": "Insufficient permissions"
}
```

### 404 Not Found
```json
{
  "detail": "Person not found"
}
```

### 409 Conflict
```json
{
  "detail": "Employee ID already exists"
}
```

### 500 Internal Server Error
```json
{
  "detail": "Internal server error",
  "request_id": "abc123"
}
```

---

## Rate Limiting (Future)

Recommended limits:
- `POST /api/*`: 100 req/min
- `GET /api/*`: 1000 req/min
- `DELETE /api/*`: 10 req/min

---

## Webhooks (Future)

Supported events:
- `person.created`
- `person.deleted`
- `attendance.checkin`
- `attendance.checkout`
- `candidate.ready`
- `candidate.converted`

---

## Pagination

All list endpoints support:
- `skip`: Number of items to skip (default 0)
- `limit`: Max items to return (default 100, max 1000)

**Example**:
```
GET /api/persons?skip=10&limit=20
```

---

## Sorting (Future)

List endpoints will support:
- `sort_by`: Field name
- `sort_order`: `asc`, `desc`

**Example**:
```
GET /api/attendance/today?sort_by=check_in&sort_order=desc
```

---

## Filtering (Future)

Advanced filtering:
- `filter`: JSON query
- `date_range`: Shorthand

**Example**:
```
GET /api/attendance/today?filter={"confidence":{"$gte":0.9}}
```

---

## Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI Schema**: http://localhost:8000/openapi.json

---

**Version**: 1.0
**Last Updated**: 2024
