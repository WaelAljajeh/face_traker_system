# ============================================================
# HEALTH CHECK MODULE - System Status and Validation
# ============================================================
# Provides comprehensive system health checks for production

import os
import logging
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


class HealthCheck:
    """System health check and status reporting."""
    
    def __init__(self, config):
        """Initialize health checker with config."""
        self.config = config
        self.issues: List[str] = []
        self.warnings: List[str] = []
        self.last_check_time = None
        
    def run_full_check(self) -> Dict:
        """Run comprehensive health check."""
        self.issues = []
        self.warnings = []
        self.last_check_time = datetime.now()
        
        logger.info("[HEALTH] Starting full system check...")
        
        checks = {
            'configuration': self._check_configuration(),
            'database': self._check_database(),
            'camera': self._check_camera_config(),
            'models': self._check_models(),
            'disk_space': self._check_disk_space(),
            'python_packages': self._check_python_packages(),
        }
        
        status = {
            'timestamp': self.last_check_time.isoformat(),
            'overall_status': self._determine_status(checks),
            'checks': checks,
            'issues': self.issues,
            'warnings': self.warnings,
        }
        
        return status
    
    def _check_configuration(self) -> Dict:
        """Validate configuration."""
        try:
            required_sections = [
                'camera', 'insightface', 'recognition', 'attendance', 'server'
            ]
            
            for section in required_sections:
                if not self.config.get_section(section):
                    self.issues.append(f"Missing config section: {section}")
            
            # Check critical thresholds
            recognition_cfg = self.config.get_section("recognition") or {}
            similarity_threshold = recognition_cfg.get("similarity_threshold", 0.40)
            
            if similarity_threshold > 0.50:
                self.warnings.append(
                    f"Similarity threshold very strict ({similarity_threshold}). "
                    "May cause false negatives. Consider 0.40-0.45."
                )
            
            camera_cfg = self.config.get_section("camera") or {}
            device_id = camera_cfg.get("device_id")
            if isinstance(device_id, int) and device_id > 5:
                self.warnings.append(
                    f"Camera device ID {device_id} seems high. "
                    "Usually 0-2 for local cameras."
                )
            
            return {
                'status': 'OK' if not self.issues else 'FAILED',
                'message': 'Configuration valid' if not self.issues else 'Configuration errors found'
            }
        
        except Exception as e:
            self.issues.append(f"Config check error: {e}")
            return {'status': 'ERROR', 'message': str(e)}
    
    def _check_database(self) -> Dict:
        """Validate face database."""
        try:
            db_cfg = self.config.get_section("recognition") or {}
            db_path = db_cfg.get("db_path", "registered_faces")
            
            if not os.path.exists(db_path):
                self.issues.append(f"Database path not found: {db_path}")
                return {'status': 'FAILED', 'message': f'Path not found: {db_path}'}
            
            # Count registered faces
            total_images = 0
            people_count = 0
            
            for person_dir in os.listdir(db_path):
                person_path = os.path.join(db_path, person_dir)
                if os.path.isdir(person_path):
                    people_count += 1
                    images = [
                        f for f in os.listdir(person_path)
                        if f.lower().endswith(('.jpg', '.jpeg', '.png'))
                    ]
                    total_images += len(images)
                    
                    if len(images) < 5:
                        self.warnings.append(
                            f"Person '{person_dir}' has only {len(images)} images. "
                            "Recommend 10+ for better accuracy."
                        )
            
            if people_count == 0:
                self.issues.append("No registered faces found in database")
                return {
                    'status': 'FAILED',
                    'message': 'Database empty',
                    'people': 0,
                    'images': 0
                }
            
            if total_images < 30:
                self.warnings.append(
                    f"Small database ({total_images} images). "
                    "Add more for better accuracy."
                )
            
            return {
                'status': 'OK',
                'message': f'Database valid with {people_count} people',
                'people': people_count,
                'images': total_images
            }
        
        except Exception as e:
            self.issues.append(f"Database check error: {e}")
            return {'status': 'ERROR', 'message': str(e)}
    
    def _check_camera_config(self) -> Dict:
        """Validate camera configuration."""
        try:
            camera_cfg = self.config.get_section("camera") or {}
            
            width = camera_cfg.get("width", 640)
            height = camera_cfg.get("height", 480)
            fps = camera_cfg.get("fps", 30)
            
            # Check reasonable bounds
            if width < 320 or width > 1920:
                self.warnings.append(f"Unusual camera width: {width}")
            
            if height < 240 or height > 1920:
                self.warnings.append(f"Unusual camera height: {height}")
            
            if fps < 15 or fps > 60:
                self.warnings.append(f"Unusual FPS setting: {fps}")
            
            return {
                'status': 'OK',
                'resolution': f'{width}x{height}',
                'fps': fps
            }
        
        except Exception as e:
            self.issues.append(f"Camera config check error: {e}")
            return {'status': 'ERROR', 'message': str(e)}
    
    def _check_models(self) -> Dict:
        """Check model file availability."""
        try:
            model_path = Path("models")
            
            # Optional liveness model
            liveness_model = model_path / "liveness_onnx.onnx"
            if not liveness_model.exists():
                self.warnings.append("Liveness model not found (optional)")
            
            return {
                'status': 'OK',
                'message': 'Model files accessible',
                'models_dir_exists': model_path.exists()
            }
        
        except Exception as e:
            self.warnings.append(f"Model check error: {e}")
            return {'status': 'WARNING', 'message': str(e)}
    
    def _check_disk_space(self) -> Dict:
        """Check available disk space."""
        try:
            import shutil
            stat = shutil.disk_usage(".")
            
            available_gb = stat.free / (1024 ** 3)
            
            if available_gb < 0.5:
                self.issues.append(f"Low disk space: {available_gb:.2f}GB available")
                return {
                    'status': 'FAILED',
                    'available_gb': available_gb
                }
            
            if available_gb < 2:
                self.warnings.append(f"Limited disk space: {available_gb:.2f}GB")
            
            return {
                'status': 'OK',
                'available_gb': available_gb
            }
        
        except Exception as e:
            self.warnings.append(f"Disk space check error: {e}")
            return {'status': 'WARNING', 'message': str(e)}
    
    def _check_python_packages(self) -> Dict:
        """Check required Python packages."""
        required_packages = {
            'cv2': 'opencv-python',
            'insightface': 'insightface',
            'numpy': 'numpy',
            'yaml': 'pyyaml',
        }
        
        missing = []
        try:
            for module, package in required_packages.items():
                try:
                    __import__(module)
                except ImportError:
                    missing.append(package)
            
            if missing:
                self.issues.append(f"Missing packages: {', '.join(missing)}")
                return {
                    'status': 'FAILED',
                    'missing': missing
                }
            
            return {
                'status': 'OK',
                'message': 'All required packages installed'
            }
        
        except Exception as e:
            self.warnings.append(f"Package check error: {e}")
            return {'status': 'WARNING', 'message': str(e)}
    
    def _determine_status(self, checks: Dict) -> str:
        """Determine overall status from checks."""
        if self.issues:
            return 'CRITICAL'
        
        failures = [
            check for check in checks.values()
            if isinstance(check, dict) and check.get('status') == 'FAILED'
        ]
        
        if failures:
            return 'FAILED'
        
        if self.warnings:
            return 'WARNING'
        
        return 'HEALTHY'
    
    def print_report(self, status: Dict):
        """Print health check report."""
        print("\n" + "=" * 60)
        print("HEALTH CHECK REPORT")
        print("=" * 60)
        print(f"Status: {status['overall_status']}")
        print(f"Time: {status['timestamp']}")
        
        for check_name, result in status['checks'].items():
            if isinstance(result, dict):
                check_status = result.get('status', 'UNKNOWN')
                print(f"\n[{check_status}] {check_name.upper()}")
                for key, value in result.items():
                    if key != 'status':
                        print(f"  {key}: {value}")
        
        if status['issues']:
            print("\n⚠️  CRITICAL ISSUES:")
            for issue in status['issues']:
                print(f"  • {issue}")
        
        if status['warnings']:
            print("\n⚠️  WARNINGS:")
            for warning in status['warnings']:
                print(f"  • {warning}")
        
        print("\n" + "=" * 60 + "\n")
    
    def is_healthy(self, status: Dict) -> bool:
        """Check if system is healthy enough to run."""
        return status['overall_status'] in ['HEALTHY', 'WARNING']
