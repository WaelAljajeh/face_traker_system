#!/usr/bin/env python3
"""
Production Face Attendance System - Safe Startup Script
=======================================================

This script provides a robust startup process with:
- System health checks
- Configuration validation
- Database integrity verification
- Graceful error handling
- Recovery suggestions
"""

import sys
import os
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from utils import Config
from utils.health_check import HealthCheck


def check_python_version():
    """Verify Python version."""
    version = sys.version_info
    if version.major < 3 or version.minor < 8:
        logger.error(f"Python 3.8+ required (found {version.major}.{version.minor})")
        sys.exit(1)
    logger.info(f"✅ Python {version.major}.{version.minor} OK")


def check_dependencies():
    """Verify all required dependencies are installed."""
    logger.info("Checking dependencies...")
    
    required = {
        'cv2': 'opencv-python',
        'numpy': 'numpy',
        'yaml': 'pyyaml',
        'insightface': 'insightface',
    }
    
    optional = {
        'requests': 'requests',
        'onnxruntime': 'onnxruntime',
    }
    
    missing_required = []
    missing_optional = []
    
    for module, package_name in required.items():
        try:
            __import__(module)
            logger.debug(f"  ✅ {package_name}")
        except ImportError:
            missing_required.append(package_name)
    
    for module, package_name in optional.items():
        try:
            __import__(module)
            logger.debug(f"  ✅ {package_name}")
        except ImportError:
            missing_optional.append(package_name)
    
    if missing_required:
        logger.error(f"Missing required packages: {', '.join(missing_required)}")
        logger.info("Install with: pip install -r requirements.txt")
        return False
    
    if missing_optional:
        logger.warning(f"Missing optional packages: {', '.join(missing_optional)}")
    
    logger.info("✅ Dependencies OK")
    return True


def load_config(config_path: str = "config.yaml"):
    """Load and validate configuration."""
    logger.info(f"Loading configuration from {config_path}...")
    
    if not os.path.exists(config_path):
        logger.error(f"Config file not found: {config_path}")
        logger.info("Ensure config.yaml exists in the project root")
        return None
    
    try:
        config = Config.load(config_path)
        logger.info("✅ Configuration loaded successfully")
        return config
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return None


def run_health_checks(config):
    """Run comprehensive health checks."""
    logger.info("Running health checks...")
    
    health = HealthCheck(config)
    status = health.run_full_check()
    
    health.print_report(status)
    
    if not health.is_healthy(status):
        logger.error(f"System health check failed: {status['overall_status']}")
        logger.error("Address issues above before starting the system")
        return False
    
    logger.info("✅ Health checks passed")
    return True


def verify_database(config):
    """Verify registered faces database."""
    logger.info("Verifying database...")
    
    recognition_cfg = config.get_section("recognition") or {}
    db_path = recognition_cfg.get("db_path", "registered_faces")
    
    if not os.path.exists(db_path):
        logger.error(f"Database path not found: {db_path}")
        logger.info("Create registered_faces directory with subdirectories per person:")
        logger.info("  mkdir -p registered_faces/person_name/")
        logger.info("  cp photos/*.jpg registered_faces/person_name/")
        return False
    
    people = []
    total_images = 0
    
    for person_dir in os.listdir(db_path):
        person_path = os.path.join(db_path, person_dir)
        if os.path.isdir(person_path):
            images = [
                f for f in os.listdir(person_path)
                if f.lower().endswith(('.jpg', '.jpeg', '.png'))
            ]
            if images:
                people.append((person_dir, len(images)))
                total_images += len(images)
    
    if not people:
        logger.error("No registered faces found in database")
        logger.info("Add face images in registered_faces/ directory structure:")
        logger.info("  registered_faces/")
        logger.info("    ├── person1/")
        logger.info("    │   ├── photo1.jpg")
        logger.info("    │   ├── photo2.jpg")
        logger.info("    │   └── ...")
        logger.info("    └── person2/")
        logger.info("        ├── photo1.jpg")
        logger.info("        └── ...")
        return False
    
    logger.info(f"✅ Database OK: {len(people)} people, {total_images} images")
    for person, count in people:
        status = "✅" if count >= 5 else "⚠️"
        logger.info(f"   {status} {person}: {count} images")
    
    return True


def verify_camera_config(config):
    """Verify camera configuration."""
    logger.info("Verifying camera configuration...")
    
    camera_cfg = config.get_section("camera") or {}
    device_id = camera_cfg.get("device_id", 0)
    
    if isinstance(device_id, int):
        logger.info(f"Camera device ID: {device_id}")
        if device_id == 2:
            logger.warning(
                "Camera device ID is 2 (may not exist on your system). "
                "Try 0 for built-in webcam, 1 for USB camera."
            )
        logger.info("ℹ️  If camera fails on startup, change device_id in config.yaml")
    else:
        logger.info(f"Camera URL/path: {device_id}")
    
    logger.info("✅ Camera configuration OK")
    return True


def create_startup_summary(config):
    """Print startup configuration summary."""
    print("\n" + "=" * 70)
    print("PRODUCTION FACE ATTENDANCE SYSTEM - STARTUP SUMMARY")
    print("=" * 70)
    
    recognition_cfg = config.get_section("recognition") or {}
    camera_cfg = config.get_section("camera") or {}
    server_cfg = config.get_section("server") or {}
    attendance_cfg = config.get_section("attendance") or {}
    
    print(f"\n📷 CAMERA:")
    print(f"   Device ID: {camera_cfg.get('device_id', 0)}")
    print(f"   Resolution: {camera_cfg.get('width', 640)}x{camera_cfg.get('height', 480)}")
    print(f"   FPS: {camera_cfg.get('fps', 30)}")
    
    print(f"\n🎯 RECOGNITION:")
    print(f"   Similarity Threshold: {recognition_cfg.get('similarity_threshold', 0.42)}")
    print(f"   Min Frames: {recognition_cfg.get('min_confident_frames', 2)}")
    print(f"   Temporal Aggregation: {recognition_cfg.get('temporal_aggregation', True)}")
    
    print(f"\n🖥️  SERVER:")
    print(f"   URL: {server_cfg.get('url', 'Not configured')}")
    print(f"   Timeout: {server_cfg.get('timeout', 20)}s")
    print(f"   Retries: {server_cfg.get('max_retries', 3)}")
    
    print(f"\n✋ ATTENDANCE:")
    print(f"   Per-Person Cooldown: {attendance_cfg.get('per_person_cooldown', 8)}s")
    print(f"   Min Confidence: {attendance_cfg.get('min_confidence_for_scan', 0.50)}")
    
    print("\n" + "=" * 70)
    print("Press Ctrl+C to quit after startup")
    print("=" * 70 + "\n")


def main():
    """Main startup sequence."""
    logger.info("Starting Production Face Attendance System...")
    logger.info("=" * 70)
    
    # Step 1: Check Python version
    logger.info("Step 1: Checking Python version...")
    check_python_version()
    
    # Step 2: Check dependencies
    logger.info("\nStep 2: Checking dependencies...")
    if not check_dependencies():
        return False
    
    # Step 3: Load configuration
    logger.info("\nStep 3: Loading configuration...")
    config = load_config("config.yaml")
    if not config:
        return False
    
    # Step 4: Run health checks
    logger.info("\nStep 4: Running health checks...")
    if not run_health_checks(config):
        return False
    
    # Step 5: Verify database
    logger.info("\nStep 5: Verifying database...")
    if not verify_database(config):
        return False
    
    # Step 6: Verify camera configuration
    logger.info("\nStep 6: Verifying camera configuration...")
    verify_camera_config(config)
    
    # Step 7: Print summary
    create_startup_summary(config)
    
    # All checks passed
    logger.info("✅ All startup checks passed!")
    logger.info("Launching production system...\n")
    
    return True


if __name__ == "__main__":
    success = main()
    
    if not success:
        logger.error("\n❌ Startup checks failed. Please fix issues above.")
        sys.exit(1)
    
    # Import and run the main application
    try:
        from app import FaceAttendanceSystem
        
        system = FaceAttendanceSystem("config.yaml")
        system.run()
    
    except KeyboardInterrupt:
        logger.info("\n✋ System stopped by user")
    
    except Exception as e:
        logger.error(f"\n❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)
