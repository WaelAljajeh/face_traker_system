#!/usr/bin/env python
"""
Production Face Attendance System - Main Application
Start this to run the REST API server.
"""

import logging
import sys
import os
import argparse
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).parent))

# Create logs directory
os.makedirs('logs', exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/attendance.log')
    ]
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Face Attendance System API")
    parser.add_argument("--config", default="config.yaml", help="Config file")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("="*70)
    logger.info("FACE ATTENDANCE SYSTEM - STARTING")
    logger.info("="*70)
    
    try:
        # Import and initialize
        logger.info("Loading configuration...")
        from utils import Config
        config = Config.load(args.config)
        
        logger.info("Initializing database...")
        from models.database import init_database
        db_config = config.get_section("database")
        db_path = db_config.get("path", "face_attendance.db")
        engine, SessionLocal = init_database(db_path, echo=False)
        
        logger.info("Initializing services...")
        from services import DatabaseService, AttendanceService, AttendanceAPIServer
        
        db_service = DatabaseService(SessionLocal)
        attendance_service = AttendanceService(
            db_service=db_service,
            cooldown_minutes=config.get("attendance.cooldown_minutes", 240),
        )
        api_server = AttendanceAPIServer(
            config=config._config,
            db_service=db_service,
            attendance_service=attendance_service,
        )
        
        # Start server
        logger.info("="*70)
        logger.info("✅ SYSTEM READY")
        logger.info("="*70)
        
        host = config.get("api.host", "0.0.0.0")
        port = config.get("api.port", 8000)
        logger.info(f"Starting API server on {host}:{port}")
        logger.info(f"Health: http://localhost:{port}/health")
        logger.info(f"API: http://localhost:{port}/api")
        logger.info("")
        
        api_server.run(host=host, port=port, workers=1)
        
    except KeyboardInterrupt:
        logger.info("Stopped by user")
        return 0
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
