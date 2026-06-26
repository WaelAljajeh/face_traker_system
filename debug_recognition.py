#!/usr/bin/env python3
"""
Run this after enrollment to debug why recognition fails.
"""
import sys
import os
import numpy as np
import cv2

# Adjust these paths to match your project structure
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.embedder import FaceEmbedder  # or wherever yours is
from services.database_service import DatabaseService
from services.vector_database import FAISSVectorDB
from models.database import init_database
from utils.config import get_appdata_dir

print("=" * 60)
print("RECOGNITION DEBUG SCRIPT")
print("=" * 60)

# 1. Initialize everything exactly like your server does
db_path = os.path.join(get_appdata_dir(), "face_attendance.db")
engine, SessionLocal = init_database(db_path)
db_service = DatabaseService(SessionLocal)
vector_db = FAISSVectorDB(embedding_dim=512)

from core.recognizer import FaceRecognizer  # the file above
recognizer = FaceRecognizer(db_service, vector_db=vector_db, normalize=True)

embedder = FaceEmbedder()

# 2. Show what's in the database
print(f"\n📊 DB has {len(recognizer.database)} embeddings in memory")
print(f"📊 FAISS has {vector_db.get_stats()} embeddings")

# 3. Test with a fresh photo (replace with your actual image path)
test_image_path = "debug_enroll_1779831008642_1779831020.jpg"  # <-- CHANGE THIS to your saved enrollment image

print(f"\n🖼️  Loading test image: {test_image_path}")
frame = cv2.imread(test_image_path)
if frame is None:
    print("❌ Cannot read image. Use an absolute path or place image next to this script.")
    sys.exit(1)

print(f"Image shape: {frame.shape}")

# 4. Extract embedding
print("\n🔬 Extracting embedding from test image...")
fresh_emb = embedder.extract_embedding(frame)

if fresh_emb is None:
    print("❌ embedder.extract_embedding() returned None — detector failed on this image")
    sys.exit(1)

# 5. Try recognition
print("\n🔍 Running recognizer.identify()...")
result, best_score, all_scores = recognizer.identify(fresh_emb, threshold=0.6)

print(f"\n📋 RESULT: recognized={result.get('recognized') if result else 'N/A'}")
print(f"📋 best_score={best_score:.6f}")
print(f"📋 person_id={result.get('person_id') if result else 'N/A'}")
print(f"📋 name={result.get('name') if result else 'N/A'}")

# 6. Manual verification: compute similarity against every stored embedding
print("\n🧮 Manual dot-product verification against all stored embeddings:")
for pid, db_emb in recognizer.database.items():
    score = float(np.dot(fresh_emb, db_emb))
    status = "✅ ABOVE 0.6" if score >= 0.6 else "❌ below 0.6"
    print(f"   pid={pid}: dot_product={score:.6f} {status}")

# 7. Check if FAISS returns the same scores
if vector_db.get_stats().get('total_embeddings', 0) > 0:
    print("\n🧮 FAISS search verification (k=5, threshold=0.0):")
    faiss_results = vector_db.search(fresh_emb, k=5, threshold=0.0)
    for pid, score in faiss_results:
        print(f"   FAISS pid={pid}: score={score:.6f}")

print("\n" + "=" * 60)
print("DIAGNOSIS GUIDE:")
print("  • If manual dot_product > 0.6 but FAISS score < 0.6:")
print("    → FAISS is using L2 distance (IndexFlatL2). Change to IndexFlatIP.")
print("  • If manual dot_product < 0.3 for your own face:")
print("    → Enrollment and recognition use different models/preprocessing.")
print("  • If manual dot_product is 0.95+ but recognition still fails:")
print("    → FAISS search() method has a bug or threshold filter is wrong.")
print("  • If no embeddings in database at all:")
print("    → Enrollment didn't actually save, or DB path is different.")
print("=" * 60)