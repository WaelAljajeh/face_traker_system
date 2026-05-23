# ============================================================
# ATTENDANCE SERVICE - Check-in Logic and Record Management
# ============================================================
# Handles:
# - Recording attendance (check-in/check-out)
# - Cooldown system (prevent duplicate check-ins)
# - Duplicate detection
# - Attendance history queries
# - Daily/monthly reports

import logging
from typing import Optional, List, Dict, Tuple
from datetime import datetime, timedelta
import threading

logger = logging.getLogger(__name__)


class AttendanceService:
    """
    Manages attendance records with:
    - Check-in/check-out logic
    - Cooldown to prevent duplicates
    - Duplicate detection
    - Reporting
    """
    
    def __init__(self, db_service,
                 cooldown_minutes: int = 240,  # 4 hours default
                 mark_checkout_after_minutes: int = 480):  # 8 hours
        """
        Initialize attendance service.
        
        Args:
            db_service: DatabaseService instance
            cooldown_minutes: Minutes before person can check-in again
            mark_checkout_after_minutes: Auto mark checkout after this duration
        """
        self.db_service = db_service
        self.cooldown_minutes = cooldown_minutes
        self.mark_checkout_after_minutes = mark_checkout_after_minutes
        
        # Cache for quick lookup
        self.last_checkin_cache: Dict[int, datetime] = {}
        self.lock = threading.Lock()
    
    def record_checkin(self, person_id: int, confidence: float,
                      track_duration: int = 0, device: str = 'webcam',
                      track_id: Optional[int] = None) -> Tuple[bool, str]:
        """
        Record check-in for person.
        
        Args:
            person_id: Person ID
            confidence: Recognition confidence (0.0-1.0)
            track_duration: How long face was tracked (ms)
            device: Device used for recognition
            track_id: Optional track ID for reference
        
        Returns:
            (success, message)
        """
        with self.lock:
            # Check cooldown
            last_checkin = self._get_last_checkin(person_id)
            if last_checkin:
                cooldown_duration = datetime.now() - last_checkin
                if cooldown_duration.total_seconds() < (self.cooldown_minutes * 60):
                    remaining = self.cooldown_minutes - int(cooldown_duration.total_seconds() / 60)
                    msg = f"Cooldown active. Next check-in in {remaining} minutes."
                    logger.info(f"[ATTENDANCE] Cooldown: {msg}")
                    return False, msg
            
            # Record check-in
            record = self.db_service.create_attendance_record(
                person_id=person_id,
                check_in_time=datetime.now(),
                confidence_avg=confidence,
                track_duration=track_duration,
                device=device,
                notes=f"track_id={track_id}" if track_id else None,
            )
            
            if record:
                # Update cache
                self.last_checkin_cache[person_id] = datetime.now()
                
                person_name = self.db_service.get_person_name(person_id)
                msg = f"Checked in: {person_name} (confidence={confidence:.2f})"
                logger.info(f"[ATTENDANCE] {msg}")
                return True, msg
            else:
                return False, "Failed to record check-in"
    
    def record_checkout(self, person_id: int, device: str = 'webcam') -> Tuple[bool, str]:
        """
        Record check-out for person.
        
        Args:
            person_id: Person ID
            device: Device used
        
        Returns:
            (success, message)
        """
        # Find latest unchecked-out record for today
        record = self.db_service.get_latest_unchecked_record(person_id)
        
        if record:
            checkout_time = datetime.now()
            duration = (checkout_time - record.check_in_time).total_seconds()
            
            self.db_service.update_checkout(
                record_id=record.record_id,
                check_out_time=checkout_time,
                duration_seconds=int(duration),
            )
            
            person_name = self.db_service.get_person_name(person_id)
            msg = f"Checked out: {person_name} (duration={int(duration/60)} min)"
            logger.info(f"[ATTENDANCE] {msg}")
            return True, msg
        else:
            return False, "No active check-in found"
    
    def is_duplicate_checkin(self, person_id: int, window_seconds: int = 5) -> bool:
        """
        Check if this is a duplicate check-in (same person within window).
        
        Args:
            person_id: Person ID
            window_seconds: Time window for duplicate detection
        
        Returns:
            True if duplicate
        """
        last_checkin = self._get_last_checkin(person_id)
        if not last_checkin:
            return False
        
        time_diff = (datetime.now() - last_checkin).total_seconds()
        return time_diff < window_seconds
    
    def _get_last_checkin(self, person_id: int) -> Optional[datetime]:
        """Get last check-in time from cache or database."""
        with self.lock:
            # Try cache first
            if person_id in self.last_checkin_cache:
                return self.last_checkin_cache[person_id]
            
            # Query database
            last_record = self.db_service.get_latest_checkin(person_id)
            if last_record:
                self.last_checkin_cache[person_id] = last_record
                return last_record
            
            return None
    
    def get_daily_attendance(self, date: datetime = None) -> Dict[int, Dict]:
        """
        Get attendance records for a day.
        
        Args:
            date: Date to query (default: today)
        
        Returns:
            Dict mapping person_id -> {'check_in': datetime, 'check_out': datetime, 'duration': int}
        """
        if date is None:
            date = datetime.now()
        
        records = self.db_service.get_attendance_by_date(date)
        
        daily = {}
        for record in records:
            person_id = record.person_id
            daily[person_id] = {
                'check_in': record.check_in_time,
                'check_out': record.check_out_time,
                'duration_minutes': int(record.duration_seconds / 60) if record.duration_seconds else 0,
                'confidence': record.confidence_avg,
                'device': record.device,
            }
        
        return daily
    
    def get_attendance_report(self, start_date: datetime, 
                             end_date: datetime) -> Dict[int, Dict]:
        """
        Get attendance report for date range.
        
        Returns:
            Dict mapping person_id -> {
                'name': str,
                'total_checkins': int,
                'total_hours': float,
                'avg_confidence': float,
                'dates': [...],
            }
        """
        records = self.db_service.get_attendance_range(start_date, end_date)
        
        report = {}
        for record in records:
            person_id = record.person_id
            
            if person_id not in report:
                person_name = self.db_service.get_person_name(person_id)
                report[person_id] = {
                    'name': person_name,
                    'total_checkins': 0,
                    'total_hours': 0.0,
                    'avg_confidence': 0.0,
                    'dates': set(),
                }
            
            report[person_id]['total_checkins'] += 1
            if record.duration_seconds:
                report[person_id]['total_hours'] += record.duration_seconds / 3600
            report[person_id]['dates'].add(record.check_in_time.date())
        
        # Convert sets to lists and calculate averages
        for person_id in report:
            report[person_id]['dates'] = sorted(list(report[person_id]['dates']))
            report[person_id]['total_days'] = len(report[person_id]['dates'])
        
        return report
    
    def get_person_today_status(self, person_id: int) -> Dict:
        """Get today's status for a person."""
        today_records = self.db_service.get_attendance_by_date(datetime.now())
        
        for record in today_records:
            if record.person_id == person_id:
                return {
                    'is_checked_in': record.check_out_time is None,
                    'check_in_time': record.check_in_time,
                    'check_out_time': record.check_out_time,
                    'duration_minutes': int(record.duration_seconds / 60) if record.duration_seconds else 0,
                    'confidence': record.confidence_avg,
                }
        
        return {'is_checked_in': False}
    
    def get_stats(self) -> dict:
        """Get attendance statistics."""
        today = datetime.now()
        today_records = self.db_service.get_attendance_by_date(today)
        
        checked_in_count = sum(1 for r in today_records if r.check_out_time is None)
        checked_out_count = sum(1 for r in today_records if r.check_out_time is not None)
        total_duration = sum(r.duration_seconds for r in today_records if r.duration_seconds)
        
        return {
            'today_checkins': len(today_records),
            'currently_checked_in': checked_in_count,
            'today_checkouts': checked_out_count,
            'total_hours_today': total_duration / 3600 if total_duration else 0,
        }
        self.executor.shutdown(wait=True)
        logger.info("[ATTENDANCE] Shutdown complete")
