import logging
from celery import shared_task
from django.utils.timezone import now
from .models import PestDetection, FarmSeason, PestAlertBroadcast, CropScanJob
from django.contrib.gis.measure import D

logger = logging.getLogger(__name__)


# ======================================================================
# CROP SCAN BACKGROUND TASK
# ======================================================================
def run_crop_scan_task(job_id: int):
    """
    Runs the full AI diagnostic pipeline in the background.
    Loaded by the CropScanSubmitView after creating a CropScanJob row.

    Lifecycle:
      PENDING → PROCESSING → COMPLETED (result stored)
                           → FAILED    (error_message stored)
    """
    from .ai_engine import process_crop_diagnostic_pipeline

    # ── Guard: job must exist ─────────────────────────────────────────
    try:
        job = CropScanJob.objects.get(id=job_id)
    except CropScanJob.DoesNotExist:
        logger.error(f"[ScanTask] Job ID={job_id} not found. Aborting.")
        return

    # Mark as processing so the frontend knows it's no longer just queued
    job.status = CropScanJob.Status.PROCESSING
    job.save(update_fields=['status'])
    logger.info(f"[ScanTask] Job #{job_id} → PROCESSING | crop='{job.crop_hint}' lang='{job.language}'")

    try:
        # image_data is a BinaryField — bytes() cast needed in Python
        image_bytes = bytes(job.image_data)

        result = process_crop_diagnostic_pipeline(
            image_bytes=image_bytes,
            crop_hint=job.crop_hint or None,
            lang_code=job.language or 'en',
        )

        job.status       = CropScanJob.Status.COMPLETED
        job.result       = result
        job.completed_at = now()
        job.save(update_fields=['status', 'result', 'completed_at'])
        logger.info(
            f"[ScanTask] Job #{job_id} → COMPLETED | "
            f"condition='{result.get('condition_type')}' | confidence={result.get('confidence')}"
        )

    except Exception as exc:
        logger.error(f"[ScanTask] Job #{job_id} → FAILED: {exc}", exc_info=True)
        job.status        = CropScanJob.Status.FAILED
        job.error_message = str(exc)
        job.completed_at  = now()
        job.save(update_fields=['status', 'error_message', 'completed_at'])


def calculate_pest_spread(detection_id):
    """
    Background task triggered after a PestDetection is saved.
    Calculates geographic spread radius (boosted by wind speed) and
    broadcasts a single PestAlertBroadcast row to all nearby farms
    that have an active crop season matching the source crop.

    Failure reasons that are logged but do NOT crash the task:
      - Detection ID does not exist in the DB
      - Source farm has no active season (fallow land at time of task)
      - No nearby farms match crop + distance criteria (silent, not an error)
    """

    # ── Guard 1: Detection must exist ────────────────────────────────
    try:
        detection = PestDetection.objects.select_related(
            'farm_season', 'farm_season__farm'
        ).get(id=detection_id)
    except PestDetection.DoesNotExist:
        logger.error(
            f"[BroadcastTask] Detection ID={detection_id} not found in the database. "
            "Task will abort."
        )
        return

    # ── Guard 2: Source season must still be active ───────────────────
    # Edge case: season could have been deactivated between detection save and task execution
    if not detection.farm_season.is_active:
        logger.warning(
            f"[BroadcastTask] Detection ID={detection_id}: source farm "
            f"'{detection.farm_season.farm.name}' is now fallow (season deactivated). "
            "Broadcast aborted — no alert will be sent."
        )
        return

    source_crop      = detection.farm_season.crop_name.strip().lower()
    source_farm_name = detection.farm_season.farm.name

    # ── Compute dynamic radius ────────────────────────────────────────
    wind_speed_kmh  = detection.weather_snapshot.get('wind_speed', 0)
    dynamic_radius_km = 10.0 + (wind_speed_kmh / 5.0)
    dynamic_radius_m  = dynamic_radius_km * 1000.0

    logger.info(
        f"[BroadcastTask] TRIGGERED | farm='{source_farm_name}' | "
        f"crop='{source_crop}' | radius={dynamic_radius_km:.1f} km"
    )

    # ── Debug pass: log every active farm considered ──────────────────
    all_active_seasons = FarmSeason.objects.filter(
        is_active=True
    ).exclude(farm=detection.farm_season.farm).select_related('farm', 'farm__user')

    logger.info(
        f"[BroadcastTask] Scanning {all_active_seasons.count()} other active farm(s) globally."
    )

    for s in all_active_seasons:
        dist_m   = s.farm.boundaries.distance(detection.detection_location)
        dist_km  = dist_m / 1000.0
        target_crop = s.crop_name.strip().lower()

        if dist_km <= dynamic_radius_km and target_crop == source_crop:
            logger.info(
                f"[BroadcastTask]   ✅ MATCH  | farm='{s.farm.name}' | "
                f"dist={dist_km:.2f} km | crop='{target_crop}'"
            )
        elif dist_km > dynamic_radius_km:
            logger.debug(
                f"[BroadcastTask]   ❌ TOO FAR | farm='{s.farm.name}' | "
                f"dist={dist_km:.2f} km (limit={dynamic_radius_km:.1f} km)"
            )
        else:
            logger.debug(
                f"[BroadcastTask]   ❌ CROP MISMATCH | farm='{s.farm.name}' | "
                f"crop='{target_crop}' (expected '{source_crop}')"
            )

    # ── Spatial query: farms within radius with same crop ─────────────
    nearby_seasons = FarmSeason.objects.filter(
        is_active=True,
        farm__boundaries__dwithin=(detection.detection_location, D(km=dynamic_radius_km))
    ).exclude(
        farm=detection.farm_season.farm
    ).select_related('farm', 'farm__user')

    affected_user_ids = set()
    max_risk_overall  = 0.0

    for season in nearby_seasons:
        distance_m = season.farm.boundaries.distance(detection.detection_location)
        risk = 100 - ((distance_m / dynamic_radius_m) * 100)

        affected_user_ids.add(season.farm.user.id)
        max_risk_overall = max(max_risk_overall, risk)

    # ── Guard 3: Only write a broadcast row if someone is actually at risk
    if not affected_user_ids:
        logger.info(
            f"[BroadcastTask] No nearby farms matched crop='{source_crop}' within "
            f"{dynamic_radius_km:.1f} km. No broadcast created (this is not an error)."
        )
        return

    PestAlertBroadcast.objects.create(
        source_detection=detection,
        max_risk_score=round(max(0.0, min(100.0, max_risk_overall)), 1),
        notified_users=list(affected_user_ids),
    )

    try:
        from .sse import push_event
        import json
        for uid in affected_user_ids:
            push_event(uid, json.dumps({"type": "new_alert"}))
    except Exception as e:
        logger.error(f"[BroadcastTask] SSE push failed: {e}")

    logger.info(
        f"[BroadcastTask] ✅ SUCCESS | Broadcast sent to {len(affected_user_ids)} user(s) "
        f"from farm='{source_farm_name}'."
    )