#!/usr/bin/env python3
"""
Face Recognition Testing & Diagnostic Tool
============================================

Tests individual components to diagnose issues.
Use this to verify your system before production.

Usage:
    python test_system.py              # Run all tests
    python test_system.py camera       # Test camera only
    python test_system.py database     # Test database only
    python test_system.py recognition  # Test recognition only
"""

import sys
import os
from pathlib import Path
import cv2
import numpy as np
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from utils import Config


def test_dependencies():
    """Test all required packages are installed."""
    print("\n" + "="*60)
    print("TEST 1: Dependencies")
    print("="*60)
    
    packages = {
        'cv2': 'opencv-python',
        'numpy': 'numpy',
        'yaml': 'pyyaml',
        'insightface': 'insightface',
    }
    
    all_ok = True
    for module, package in packages.items():
        try:
            __import__(module)
            print(f"✅ {package}")
        except ImportError:
            print(f"❌ {package} - INSTALL WITH: pip install {package}")
            all_ok = False
    
    return all_ok


def test_configuration():
    """Test configuration loading."""
    print("\n" + "="*60)
    print("TEST 2: Configuration")
    print("="*60)
    
    if not os.path.exists("config.yaml"):
        print("❌ config.yaml not found")
        return False
    
    try:
        config = Config.load("config.yaml")
        
        # Check required sections
        sections = ['camera', 'insightface', 'recognition', 'server']
        for section in sections:
            cfg = config.get_section(section)
            if cfg:
                print(f"✅ {section} section found")
            else:
                print(f"⚠️  {section} section missing (might be OK)")
        
        # Show key settings
        print("\nKey Settings:")
        recognition_cfg = config.get_section("recognition") or {}
        print(f"  - Similarity Threshold: {recognition_cfg.get('similarity_threshold', 0.42)}")
        print(f"  - Min Frames: {recognition_cfg.get('min_confident_frames', 2)}")
        
        camera_cfg = config.get_section("camera") or {}
        print(f"  - Camera Device: {camera_cfg.get('device_id', 0)}")
        
        return True
    
    except Exception as e:
        print(f"❌ Config error: {e}")
        return False


def test_detector():
    """Test face detector initialization."""
    print("\n" + "="*60)
    print("TEST 3: Face Detector (InsightFace)")
    print("="*60)
    
    try:
        from core import FaceDetector
        
        print("Initializing detector...")
        detector = FaceDetector(
            model_name='buffalo_l',
            confidence_threshold=0.70
        )
        
        print("✅ Detector initialized successfully")
        
        # Test detection on a dummy frame
        test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        detections, elapsed = detector.detect(test_frame)
        print(f"✅ Detection inference works ({elapsed:.1f}ms for empty frame)")
        
        return True
    
    except Exception as e:
        print(f"❌ Detector error: {e}")
        print("   Make sure InsightFace is installed: pip install insightface>=0.7.3")
        return False


def test_database():
    """Test face database loading."""
    print("\n" + "="*60)
    print("TEST 4: Face Database")
    print("="*60)
    
    db_path = "registered_faces"
    
    if not os.path.exists(db_path):
        print(f"❌ {db_path}/ directory not found")
        print(f"   Create with: mkdir -p {db_path}")
        return False
    
    try:
        from core import FaceDetector, FaceRecognizer
        
        # Initialize detector first
        detector = FaceDetector()
        
        # Load recognizer
        print(f"Loading database from {db_path}/...")
        recognizer = FaceRecognizer(db_path, detector=detector)
        
        if not recognizer.database_embeddings:
            print(f"⚠️  No faces loaded from database")
            print(f"   Structure should be:")
            print(f"   {db_path}/")
            print(f"     └── person1/")
            print(f"         ├── photo1.jpg")
            print(f"         └── photo2.jpg")
            return False
        
        print(f"✅ Database loaded: {len(recognizer.database)} people")
        for person, count in recognizer.database.items():
            print(f"   - {person}: {count} images")
        
        return True
    
    except Exception as e:
        print(f"❌ Database error: {e}")
        return False


def test_recognition():
    """Test face recognition on database images."""
    print("\n" + "="*60)
    print("TEST 5: Face Recognition")
    print("="*60)
    
    try:
        from core import FaceDetector, FaceRecognizer
        
        detector = FaceDetector()
        recognizer = FaceRecognizer("registered_faces", detector=detector)
        
        if not recognizer.database:
            print("❌ Database empty - cannot test recognition")
            return False
        
        # Test recognition on first person's first image
        first_person = list(recognizer.database.keys())[0]
        first_image = None
        
        for img_file in os.listdir(f"registered_faces/{first_person}"):
            if img_file.lower().endswith(('.jpg', '.jpeg', '.png')):
                first_image = f"registered_faces/{first_person}/{img_file}"
                break
        
        if not first_image:
            print(f"❌ No test image found for {first_person}")
            return False
        
        # Load and test
        img = cv2.imread(first_image)
        if img is None:
            print(f"❌ Failed to load {first_image}")
            return False
        
        # Detect face
        detections, _ = detector.detect(img)
        if not detections:
            print(f"❌ Could not detect face in {first_image}")
            print("   Check image quality - ensure clear face with good lighting")
            return False
        
        # Recognize
        embedding = detections[0]['embedding']
        name, distance, scores = recognizer.identify(embedding, threshold=0.42)
        
        print(f"Test image: {first_image}")
        print(f"Expected: {first_person}")
        print(f"Recognized: {name}")
        print(f"Distance: {distance:.3f}")
        
        if name == first_person:
            print("✅ Recognition successful!")
            return True
        else:
            print("⚠️  Recognition failed or uncertain")
            print("   Scores:")
            for person, score in sorted(scores.items(), key=lambda x: x[1]):
                marker = "→" if person == name else " "
                print(f"     {marker} {person}: {score:.3f}")
            print("   Try lowering similarity_threshold in config.yaml")
            return False
    
    except Exception as e:
        print(f"❌ Recognition error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_camera(camera_id=0):
    """Test camera access."""
    print("\n" + "="*60)
    print(f"TEST 6: Camera (Device {camera_id})")
    print("="*60)
    
    cap = cv2.VideoCapture(camera_id)
    
    if not cap.isOpened():
        print(f"❌ Cannot open camera {camera_id}")
        print("   Try different device_id in config.yaml: 0, 1, 2, etc.")
        return False
    
    # Try to read a frame
    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        print(f"❌ Could not read frame from camera {camera_id}")
        return False
    
    print(f"✅ Camera {camera_id} works")
    print(f"   Resolution: {frame.shape[1]}x{frame.shape[0]}")
    print(f"   Channels: {frame.shape[2]}")
    
    return True


def test_server_config():
    """Test server configuration."""
    print("\n" + "="*60)
    print("TEST 7: Server Configuration")
    print("="*60)
    
    try:
        config = Config.load("config.yaml")
        server_cfg = config.get_section("server") or {}
        
        url = server_cfg.get("url", "http://localhost")
        endpoint = server_cfg.get("endpoint", "/scan")
        timeout = server_cfg.get("timeout", 20)
        
        print(f"✅ Server URL: {url}{endpoint}")
        print(f"✅ Timeout: {timeout}s")
        print(f"✅ Max Retries: {server_cfg.get('max_retries', 3)}")
        
        # Try to reach server
        try:
            import requests
            print("\nTesting connectivity...")
            response = requests.head(url, timeout=5)
            print(f"✅ Server reachable (HTTP {response.status_code})")
            return True
        except Exception as e:
            print(f"⚠️  Could not reach server: {e}")
            print("   This is OK if server is not running yet")
            return True  # Not a failure
    
    except Exception as e:
        print(f"❌ Server config error: {e}")
        return False


def run_all_tests():
    """Run all tests."""
    print("\n")
    print("╔" + "="*58 + "╗")
    print("║" + " "*15 + "FACE RECOGNITION SYSTEM TEST" + " "*14 + "║")
    print("╚" + "="*58 + "╝")
    
    tests = [
        ("Dependencies", test_dependencies),
        ("Configuration", test_configuration),
        ("Face Detector", test_detector),
        ("Face Database", test_database),
        ("Face Recognition", test_recognition),
        ("Server Config", test_server_config),
    ]
    
    # Camera test is special - read from config
    config = Config.load("config.yaml") if os.path.exists("config.yaml") else None
    camera_id = 0
    if config:
        camera_cfg = config.get_section("camera") or {}
        camera_id = camera_cfg.get("device_id", 0)
    
    tests.append((f"Camera (Device {camera_id})", lambda: test_camera(camera_id)))
    
    results = {}
    for test_name, test_func in tests:
        try:
            results[test_name] = test_func()
        except Exception as e:
            logger.error(f"Test {test_name} crashed: {e}")
            results[test_name] = False
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        marker = "✅" if result else "❌"
        print(f"{marker} {test_name}")
    
    print("="*60)
    print(f"Result: {passed}/{total} tests passed")
    print("="*60)
    
    if passed == total:
        print("\n🎉 All tests passed! System is ready for production.")
        return True
    else:
        print(f"\n⚠️  {total - passed} tests failed. Fix issues above before running production.")
        return False


if __name__ == "__main__":
    # Allow running specific tests
    if len(sys.argv) > 1:
        test_name = sys.argv[1].lower()
        
        test_map = {
            'dependencies': test_dependencies,
            'config': test_configuration,
            'detector': test_detector,
            'database': test_database,
            'recognition': test_recognition,
            'server': test_server_config,
            'camera': lambda: test_camera(0),
        }
        
        if test_name in test_map:
            result = test_map[test_name]()
            sys.exit(0 if result else 1)
        else:
            print(f"Unknown test: {test_name}")
            print(f"Available: {', '.join(test_map.keys())}")
            sys.exit(1)
    
    # Run all tests
    success = run_all_tests()
    sys.exit(0 if success else 1)
