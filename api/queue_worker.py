import threading
import time
import logging
from django.utils.timezone import now

logger = logging.getLogger(__name__)

# Flag to prevent spawning duplicate worker threads (e.g. Django dev server runs ready() twice)
_worker_started = False

def process_queue():
    from .models import CropScanJob, UserNotification
    from .tasks import run_crop_scan_task
    
    logger.info("CropScanJob Queue Worker Started.")
    
    while True:
        try:
            # Look for pending jobs, ordered by oldest first
            job = CropScanJob.objects.filter(status=CropScanJob.Status.PENDING).order_by('created_at').first()
            if job:
                # Mark as processing immediately to prevent re-picking
                job.status = CropScanJob.Status.PROCESSING
                job.save(update_fields=['status'])
                
                try:
                    # Run the existing synchronous task pipeline
                    run_crop_scan_task(job.id)
                    
                    # Refresh from DB to get the new status from run_crop_scan_task
                    job.refresh_from_db()
                    
                    if job.status == CropScanJob.Status.COMPLETED:
                        notification = UserNotification.objects.create(
                            user=job.user,
                            title="Crop Scan Complete",
                            message=f"Your scan for {job.crop_hint or 'Crop'} is ready. Diagnosis: {job.result.get('primary_diagnosis', 'Unknown')}",
                            link=f"/pest-history?highlight_id={job.id}"
                        )
                        from .sse import push_event
                        import json
                        push_event(job.user.id, json.dumps({
                            "type": "job_completed", 
                            "job_id": job.id, 
                            "crop": job.crop_hint or "Crop",
                            "notification": {
                                "id": notification.id,
                                "title": notification.title,
                                "message": notification.message,
                                "link": notification.link,
                                "created_at": notification.created_at.isoformat(),
                                "is_read": False
                            }
                        }))
                    else:
                        notification = UserNotification.objects.create(
                            user=job.user,
                            title="Crop Scan Failed",
                            message=f"Failed to scan {job.crop_hint or 'Crop'}. Please try again.",
                            link=f"/pest-history"
                        )
                        from .sse import push_event
                        import json
                        push_event(job.user.id, json.dumps({
                            "type": "job_failed", 
                            "job_id": job.id, 
                            "crop": job.crop_hint or "Crop",
                            "notification": {
                                "id": notification.id,
                                "title": notification.title,
                                "message": notification.message,
                                "link": notification.link,
                                "created_at": notification.created_at.isoformat(),
                                "is_read": False
                            }
                        }))

                except Exception as e:
                    logger.error(f"Worker thread error processing job {job.id}: {e}")
            else:
                # No jobs, sleep before polling again
                time.sleep(2)
        except Exception as e:
            logger.error(f"Worker thread encountered an unexpected error: {e}")
            time.sleep(5)

def start_worker():
    global _worker_started
    if _worker_started:
        logger.info("Queue worker already running — skipping duplicate start.")
        return

    _worker_started = True
    thread = threading.Thread(target=process_queue, daemon=True, name="CropScanQueueWorker")
    thread.start()
    logger.info("CropScan Queue Worker thread launched.")
