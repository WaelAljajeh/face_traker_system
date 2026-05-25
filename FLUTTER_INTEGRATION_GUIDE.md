# Flutter Integration Guide - Face Attendance API

## System Flow

```
1. REGISTRATION PHASE
   ├─ Create Person (POST /api/persons)
   ├─ Enroll Face (POST /api/enrollment/manual)
   └─ Embedding is extracted and stored in database
   
2. RECOGNITION PHASE
   ├─ Capture face image
   ├─ Send for recognition (POST /api/recognize)
   └─ Get matched person or unknown
```

## API Base URL

```
http://YOUR_SERVER_IP:8000
```

Example for local testing:
```
http://192.168.1.X:8000  (replace X with your machine IP)
http://localhost:8000     (if testing on same machine)
```

---

## ✅ HEALTH CHECK

### 1. Check Server Status

**Endpoint:** `GET /health`

**cURL:**
```bash
curl -X GET "http://localhost:8000/health"
```

**Response:**
```json
{
  "status": "ok",
  "time": "2026-05-25T10:30:45.123456"
}
```

**Flutter:**
```dart
final response = await http.get(
  Uri.parse('http://localhost:8000/health'),
);
```

---

## 👤 PERSON MANAGEMENT

### 1. Create a New Person (Registration Step 1)

**Endpoint:** `POST /api/persons`

**Parameters:**
- `name` (query string, required): Person's name

**cURL:**
```bash
curl -X POST "http://localhost:8000/api/persons?name=John%20Doe"
```

**Response:**
```json
{
  "success": true,
  "person_id": 1,
  "name": "John Doe"
}
```

**Flutter:**
```dart
import 'package:http/http.dart' as http;

Future<Map<String, dynamic>> createPerson(String name) async {
  final response = await http.post(
    Uri.parse('http://localhost:8000/api/persons?name=$name'),
  );
  
  if (response.statusCode == 200) {
    return jsonDecode(response.body);
  } else {
    throw Exception('Failed to create person: ${response.body}');
  }
}
```

---

### 2. Get All Registered Persons

**Endpoint:** `GET /api/persons`

**cURL:**
```bash
curl -X GET "http://localhost:8000/api/persons"
```

**Response:**
```json
{
  "success": true,
  "count": 3,
  "persons": [
    {
      "person_id": 1,
      "name": "John Doe",
      "employee_id": null,
      "is_active": true,
      "created_at": "2026-05-25T10:00:00"
    },
    {
      "person_id": 2,
      "name": "Jane Smith",
      "employee_id": null,
      "is_active": true,
      "created_at": "2026-05-25T10:05:00"
    }
  ]
}
```

**Flutter:**
```dart
Future<List<Map<String, dynamic>>> getPersons() async {
  final response = await http.get(
    Uri.parse('http://localhost:8000/api/persons'),
  );
  
  if (response.statusCode == 200) {
    final data = jsonDecode(response.body);
    return List<Map<String, dynamic>>.from(data['persons']);
  } else {
    throw Exception('Failed to get persons');
  }
}
```

---

## 📸 ENROLLMENT (Registration Step 2)

### Enroll Person with Face Image

**Endpoint:** `POST /api/enrollment/manual`

**Parameters (multipart form-data):**
- `name` (form field, required): Person's name
- `person_id` (form field, optional): Person ID (if already created). If not provided, person will be created automatically
- `file` (file upload, required): Face image file (JPEG/PNG)

**cURL:**
```bash
curl -X POST "http://localhost:8000/api/enrollment/manual" \
  -F "person_id=1" \
  -F "name=John Doe" \
  -F "file=@/path/to/face_image.jpg"
```

**Response:**
```json
{
  "success": true,
  "person_id": 1,
  "name": "John Doe",
  "message": "Face enrolled successfully"
}
```

**Flutter (using image_picker and http):**
```dart
import 'package:image_picker/image_picker.dart';
import 'package:http/http.dart' as http;

Future<Map<String, dynamic>> enrollFace({
  required int personId,
  required String name,
  required File imageFile,
}) async {
  try {
    var request = http.MultipartRequest(
      'POST',
      Uri.parse('http://localhost:8000/api/enrollment/manual'),
    );

    request.fields['person_id'] = personId.toString();
    request.fields['name'] = name;
    request.files.add(await http.MultipartFile.fromPath('file', imageFile.path));

    var response = await request.send();
    var responseData = await response.stream.bytesToString();
    
    if (response.statusCode == 200) {
      return jsonDecode(responseData);
    } else {
      throw Exception('Enrollment failed: ${response.statusCode}');
    }
  } catch (e) {
    throw Exception('Error during enrollment: $e');
  }
}

// Usage
final picker = ImagePicker();
final image = await picker.pickImage(source: ImageSource.camera);

if (image != null) {
  final result = await enrollFace(
    personId: 1,
    name: 'John Doe',
    imageFile: File(image.path),
  );
  print(result); // {"success": true, "person_id": 1, ...}
}
```

---

## 🔍 FACE RECOGNITION

### Recognize Face from Image

**Endpoint:** `POST /api/recognize`

**Parameters (multipart form-data):**
- `file` (file upload, required): Face image file (JPEG/PNG)

**cURL:**
```bash
curl -X POST "http://localhost:8000/api/recognize" \
  -F "file=@/path/to/face_image.jpg"
```

**Response (If face recognized):**
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
    "2": 0.45,
    "3": 0.38
  }
}
```

**Response (If face NOT recognized):**
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
    "2": 0.42,
    "3": 0.38
  }
}
```

**Response (If no face in image):**
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

**Flutter:**
```dart
Future<Map<String, dynamic>> recognizeFace(File imageFile) async {
  try {
    var request = http.MultipartRequest(
      'POST',
      Uri.parse('http://localhost:8000/api/recognize'),
    );

    request.files.add(await http.MultipartFile.fromPath('file', imageFile.path));

    var response = await request.send();
    var responseData = await response.stream.bytesToString();
    
    if (response.statusCode == 200) {
      return jsonDecode(responseData);
    } else {
      throw Exception('Recognition failed: ${response.statusCode}');
    }
  } catch (e) {
    throw Exception('Error during recognition: $e');
  }
}

// Usage
final picker = ImagePicker();
final image = await picker.pickImage(source: ImageSource.camera);

if (image != null) {
  final result = await recognizeFace(File(image.path));
  
  if (result['success'] && result['recognized']) {
    print('✅ Recognized: ${result['name']} (Confidence: ${result['confidence']})');
  } else if (result['success'] && !result['recognized']) {
    print('❌ Unknown person');
  } else {
    print('⚠️ No face detected');
  }
}
```

---

## 📊 Response Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad request (invalid image, no face detected) |
| 500 | Server error |

---

## 🎯 Complete Flutter Workflow Example

```dart
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:http/http.dart' as http;
import 'dart:io';
import 'dart:convert';

class FaceAttendanceApp extends StatefulWidget {
  @override
  _FaceAttendanceAppState createState() => _FaceAttendanceAppState();
}

class _FaceAttendanceAppState extends State<FaceAttendanceApp> {
  final String API_URL = 'http://192.168.1.100:8000'; // Change to your server IP
  final picker = ImagePicker();

  // REGISTRATION WORKFLOW
  Future<void> registerNewPerson() async {
    // Step 1: Create person
    final nameController = TextEditingController();
    
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Enter Name'),
        content: TextField(
          controller: nameController,
          hint: 'Person name',
        ),
        actions: [
          TextButton(
            onPressed: () async {
              String name = nameController.text;
              
              // Create person
              var createResponse = await http.post(
                Uri.parse('$API_URL/api/persons?name=$name'),
              );
              
              if (createResponse.statusCode == 200) {
                var personData = jsonDecode(createResponse.body);
                int personId = personData['person_id'];
                
                // Step 2: Capture face image for enrollment
                final image = await picker.pickImage(source: ImageSource.camera);
                if (image != null) {
                  // Step 3: Enroll face
                  var enrollResponse = await http.MultipartRequest(
                    'POST',
                    Uri.parse('$API_URL/api/enrollment/manual'),
                  )
                    ..fields['person_id'] = personId.toString()
                    ..fields['name'] = name
                    ..files.add(await http.MultipartFile.fromPath('file', image.path))
                    ..send();
                  
                  if (enrollResponse.statusCode == 200) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text('✅ Registration successful!')),
                    );
                  }
                }
              }
              
              Navigator.pop(context);
            },
            child: Text('Register'),
          ),
        ],
      ),
    );
  }

  // RECOGNITION WORKFLOW
  Future<void> recognizeAttendee() async {
    final image = await picker.pickImage(source: ImageSource.camera);
    
    if (image != null) {
      var recognizeResponse = await http.MultipartRequest(
        'POST',
        Uri.parse('$API_URL/api/recognize'),
      )
        ..files.add(await http.MultipartFile.fromPath('file', image.path))
        ..send();

      var responseData = await recognizeResponse.stream.bytesToString();
      
      if (recognizeResponse.statusCode == 200) {
        var result = jsonDecode(responseData);
        
        if (result['recognized']) {
          showDialog(
            context: context,
            builder: (context) => AlertDialog(
              title: Text('✅ Recognized'),
              content: Text(
                'Name: ${result['name']}\n'
                'Confidence: ${(result['confidence'] * 100).toStringAsFixed(1)}%',
              ),
              actions: [TextButton(onPressed: () => Navigator.pop(context), child: Text('OK'))],
            ),
          );
        } else {
          showDialog(
            context: context,
            builder: (context) => AlertDialog(
              title: Text('❌ Unknown Person'),
              content: Text('This person is not registered.'),
              actions: [TextButton(onPressed: () => Navigator.pop(context), child: Text('OK'))],
            ),
          );
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Face Attendance')),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            ElevatedButton(
              onPressed: registerNewPerson,
              child: Text('📝 Register New Person'),
            ),
            SizedBox(height: 20),
            ElevatedButton(
              onPressed: recognizeAttendee,
              child: Text('🔍 Recognize Attendee'),
            ),
          ],
        ),
      ),
    );
  }
}
```

---

## ⚙️ Important Configuration

### Server IP Address
When deploying, update your Flutter app to use the correct server IP:

```dart
// For local testing
const String API_URL = 'http://localhost:8000';

// For network testing (find your PC IP using: ipconfig on Windows)
const String API_URL = 'http://192.168.1.100:8000';
```

### CORS Configuration
The API is configured to accept requests from any origin (`allow_origins=["*"]`), so no additional CORS setup is needed for Flutter.

---

## 🧪 Testing Checklist

- [ ] Server runs without errors: `python app.py`
- [ ] Health check passes: `GET /health`
- [ ] Can create person: `POST /api/persons`
- [ ] Can enroll face: `POST /api/enrollment/manual` (with face image)
- [ ] Can recognize face: `POST /api/recognize` (with face image)
- [ ] Flutter app connects to server
- [ ] Flutter can register new person
- [ ] Flutter can recognize registered faces

---

## 🚀 Quick Start

1. **Start the server:**
   ```bash
   cd c:\Users\Laptop Home\Documents\face_attendance
   python app.py
   ```

2. **Test health check:**
   ```bash
   curl -X GET "http://localhost:8000/health"
   ```

3. **View interactive API docs:**
   ```
   http://localhost:8000/docs
   ```

4. **Update Flutter app with server IP and start testing!**
