# Developer Guide - Face Recognition Attendance System

## Overview for Developers

This guide helps developers understand the system architecture and extend functionality.

## Code Organization Principles

### 1. Separation of Concerns
- **Models** (`models/`): Data structures only
- **Core** (`core/`): Algorithm implementations (detection, tracking, quality)
- **Services** (`services/`): Business logic (enrollment, attendance, recognition)
- **Utils** (`utils/`): Utilities and helpers
- **API** (`services/api_server.py`): HTTP interface

### 2. Thread Safety
All shared data structures use `threading.Lock()`:
```python
with self.lock:
    self.state_variable = new_value
```

### 3. Configuration-Driven
All parameters go to `config.yaml`, not hardcoded:
```python
threshold = self.config.get("section.key", default_value)
```

## Adding New Features

### 1. Add New Database Entity

**Step 1**: Update `models/database.py`
```python
from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime

class NewEntity(Base):
    __tablename__ = 'new_entities'
    
    id = Column(Integer, primary_key=True)
    data = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
```

**Step 2**: Add CRUD to `DatabaseService`
```python
def create_new_entity(self, data: str):
    entity = NewEntity(data=data)
    self.session.add(entity)
    self.session.commit()
    return entity.id
```

**Step 3**: Add API endpoint
```python
@app.post("/api/entities")
def create_entity(data: str):
    entity_id = db_service.create_new_entity(data)
    return {"id": entity_id}
```

### 2. Add New Recognition Algorithm

**Step 1**: Create new service in `services/new_recognizer.py`
```python
class NewRecognizer:
    def recognize(self, embedding, threshold):
        # Your algorithm
        return name, distance
```

**Step 2**: Update `FaceAttendanceSystem.__init__`
```python
if use_new_recognizer:
    self.recognizer = NewRecognizer(...)
else:
    self.recognizer = RecognitionEngine(...)
```

**Step 3**: Use through interface (polymorphism)
```python
name, distance = self.recognizer.recognize(embedding, threshold)
```

### 3. Add New Quality Filter

**Step 1**: Extend `QualityFilter` in `core/quality.py`
```python
def check_new_metric(self, frame, bbox):
    # Compute metric
    if metric < threshold:
        return False, score, {"new_metric": "failed"}
    return True, score, {}
```

**Step 2**: Call from `assess()`
```python
pass_checks = [
    self.check_blur(frame, bbox),
    self.check_brightness(frame, bbox),
    self.check_new_metric(frame, bbox),  # New
]
```

### 4. Add New API Endpoint

**Step 1**: Add to `AttendanceAPIServer`
```python
@self.app.get("/api/new_endpoint")
async def new_endpoint(param: str):
    """New endpoint description."""
    result = self.do_something(param)
    return {"result": result}
```

**Step 2**: Add to requirements if needed
**Step 3**: Test with curl
```bash
curl http://localhost:8000/api/new_endpoint?param=value
```

## Testing Pattern

### Unit Test Example
```python
# tests/test_vector_database.py
import pytest
from services.vector_database import FAISSVectorDB

def test_add_and_search():
    db = FAISSVectorDB(embedding_dim=512)
    
    # Add embedding
    embedding = np.random.randn(512).astype(np.float32)
    embedding /= np.linalg.norm(embedding)
    db.add_embedding(1, embedding, {"person": "test"})
    
    # Search
    results = db.search(embedding, k=1)
    assert results[0][0] == 1  # Retrieved same ID
    assert results[0][1] < 0.01  # Distance near zero
```

### Integration Test Example
```python
def test_attendance_flow():
    # Initialize system
    system = FaceAttendanceSystem("test_config.yaml")
    
    # Create person
    db_service.create_person("Test User", "TST001")
    
    # Add embedding
    embedding = detector.extract_embedding(test_image)
    db_service.save_embedding(1, embedding, confidence=0.95)
    
    # Record attendance
    attendance_service.record_checkin(1, confidence=0.95)
    
    # Verify
    records = attendance_service.get_daily_attendance(today)
    assert len(records) == 1
    assert records[0].person_id == 1
```

## Performance Optimization

### 1. Profiling
```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# Your code
main_loop()

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats("cumulative")
stats.print_stats(20)
```

### 2. Memory Profiling
```bash
pip install memory-profiler
python -m memory_profiler app.py
```

### 3. Common Bottlenecks
- **Detection**: Use batch processing
- **FAISS Search**: Use IVF index for scale
- **Database**: Add indexes, use connection pooling
- **Embedding Storage**: Cache in memory, use compression

## Adding New Modules

### Create a New Service

**File**: `services/my_service.py`
```python
import logging
from threading import Lock

logger = logging.getLogger(__name__)

class MyService:
    def __init__(self, config):
        self.config = config
        self.lock = Lock()
    
    def do_work(self, data):
        with self.lock:
            result = self._process(data)
        return result
    
    def _process(self, data):
        logger.debug(f"Processing: {data}")
        return data
```

**Update**: `services/__init__.py`
```python
from .my_service import MyService

__all__ = [
    "MyService",
    # ... other exports
]
```

**Use in app**:
```python
from services import MyService

my_service = MyService(config)
```

## Configuration Extension

### Add New Config Section

**config.yaml**:
```yaml
my_feature:
  enabled: true
  parameter1: 0.5
  parameter2: 100
```

**Access in code**:
```python
my_cfg = self.config.get_section("my_feature")
enabled = my_cfg.get("enabled", False)
param1 = my_cfg.get("parameter1", 0.5)
```

## Debugging Tips

### Enable Debug Logging
```python
logging.getLogger().setLevel(logging.DEBUG)
```

### Add Timing
```python
import time

start = time.perf_counter()
# ... code ...
elapsed = time.perf_counter() - start
logger.debug(f"Operation took {elapsed*1000:.1f}ms")
```

### Thread Debugging
```python
import threading

for thread in threading.enumerate():
    logger.debug(f"Thread: {thread.name}, alive: {thread.is_alive()}")
```

### Database Debugging
```python
# Enable SQL logging
import logging
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
```

## Common Issues & Solutions

### Issue: Embeddings Not Saving
```python
# Check: DatabaseService uses session.commit()
# Verify: Person exists before saving embedding
# Test: Run database_service tests
```

### Issue: FAISS Search Returns Wrong Results
```python
# Check: Embeddings are normalized (L2 norm = 1)
# Verify: Index type matches metric (flat for cosine)
# Test: Add known embedding, search for it
```

### Issue: Track IDs Keep Changing
```python
# Check: IOU threshold too low (increase from 0.5)
# Verify: Detection confidence threshold reasonable
# Adjust: Max age parameter if tracks expire too fast
```

### Issue: Unknown Candidates Never Merge
```python
# Check: Quality filter not too strict
# Verify: Merge threshold appropriate (default 0.75)
# Ensure: Enough frames collected for averaging
```

## Extending to Multi-Camera

### Current Architecture (Single Camera)
```
Camera → Queue → Detection → Tracking → Recognition → Attendance
```

### Multi-Camera Architecture
```
Camera 1 → Queue → \
Camera 2 → Queue → → Detection → Tracking → Recognition
Camera 3 → Queue → /
```

**Implementation**:
```python
# Modify main loop
for camera_id, camera in self.cameras.items():
    frame_data = camera.get_frame()
    if frame_data:
        frame_queue.put((camera_id, frame_data))

# In inference loop
camera_id, frame = frame_queue.get()
detections = self.detector.detect(frame)
# Associate with camera_id for spatial tracking
```

## Scaling to Large Embeddings

### Current: FAISS Flat Index
- Good for < 100K embeddings
- Exact search, slow at scale

### Production: FAISS IVF Index
```python
import faiss

# In FAISSVectorDB.__init__
if num_embeddings > 100000:
    nlist = int(np.sqrt(num_embeddings / 39))
    quantizer = faiss.IndexFlatL2(embedding_dim)
    index = faiss.IndexIVFFlat(quantizer, embedding_dim, nlist)
else:
    index = faiss.IndexFlatL2(embedding_dim)
```

## Release Checklist

- [ ] All tests passing
- [ ] Code reviewed
- [ ] Configuration validated
- [ ] Logging at appropriate levels
- [ ] Documentation updated
- [ ] Performance benchmarked
- [ ] Memory leaks checked
- [ ] Database migrations tested
- [ ] API contract verified
- [ ] Security audit completed

## Code Style

### Python Standards
- Follow PEP 8
- Type hints for public methods
- Docstrings for classes and functions
- Constants in UPPER_CASE

### Example:
```python
def process_embedding(
    embedding: np.ndarray,
    threshold: float = 0.5
) -> Tuple[bool, float]:
    """
    Process embedding against threshold.
    
    Args:
        embedding: Face embedding vector
        threshold: Similarity threshold
        
    Returns:
        Tuple of (is_match, similarity_score)
    """
    similarity = compute_similarity(embedding)
    return similarity > threshold, similarity
```

## Resources

- [InsightFace Documentation](https://insightface.ai/)
- [FAISS Documentation](https://github.com/facebookresearch/faiss)
- [ByteTrack Paper](https://arxiv.org/abs/2110.06864)
- [SQLAlchemy Docs](https://docs.sqlalchemy.org/)
- [FastAPI Docs](https://fastapi.tiangolo.com/)

---

**Last Updated**: 2024
**Maintainer**: Development Team
