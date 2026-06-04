"""Webhook-based trigger for S3/MinIO bucket notifications.

Receives HTTP POST notifications when new objects are created in storage,
then triggers the processing pipeline for the referenced file.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import structlog
from fastapi import APIRouter, Depends, Request, Response

from common.auth.service_auth import verify_service
from src.models import WebhookNotification

if TYPE_CHECKING:
    from src.processing.pipeline import ProcessingPipeline

logger = structlog.get_logger(__name__)

router = APIRouter()

# Module-level pipeline reference, set during app startup
_pipeline: "ProcessingPipeline | None" = None


def set_pipeline(pipeline: "ProcessingPipeline") -> None:
    """Set the processing pipeline reference for webhook handlers.

    Called during application startup to wire the pipeline into the
    webhook router without circular imports.
    """
    global _pipeline  # noqa: PLW0603
    _pipeline = pipeline


@router.post("/notify")
async def handle_notification(
    request: Request,
    service_id: str = Depends(verify_service),
) -> Response:
    """Handle S3/MinIO bucket notification webhook.

    Parses the event payload and triggers processing for new object
    creation events within the configured watch prefix.

    Supports both MinIO-style and AWS S3-style notification payloads.
    """
    if _pipeline is None:
        logger.error("webhook_no_pipeline")
        return Response(status_code=503, content="Service not ready")

    try:
        body: dict[str, Any] = await request.json()
    except Exception as exc:
        logger.warning("webhook_invalid_payload", error=str(exc))
        return Response(status_code=400, content="Invalid JSON payload")

    notifications = _parse_notifications(body)

    if not notifications:
        logger.debug("webhook_no_relevant_events")
        return Response(status_code=200, content="No relevant events")

    for notification in notifications:
        logger.info(
            "webhook_processing_file",
            object_key=notification.object_key,
            event=notification.event_name,
            size=notification.object_size,
        )
        try:
            await _pipeline.process_file(notification.object_key)
        except Exception as exc:
            logger.error(
                "webhook_processing_error",
                object_key=notification.object_key,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    return Response(status_code=200, content="OK")


def _parse_notifications(body: dict[str, Any]) -> list[WebhookNotification]:
    """Parse S3/MinIO notification payload into structured notifications.

    Handles both the AWS S3 event notification format and MinIO webhook format.
    Only returns notifications for object creation events.
    """
    notifications: list[WebhookNotification] = []

    # MinIO/S3 notification format: {"Records": [...]}
    records = body.get("Records", [])
    if not records and "EventName" in body:
        # Single-record MinIO format
        records = [body]

    for record in records:
        event_name = record.get("eventName", record.get("EventName", ""))

        # Only process object creation events
        if "ObjectCreated" not in event_name and "Put" not in event_name:
            continue

        s3_data = record.get("s3", {})
        bucket_info = s3_data.get("bucket", {})
        object_info = s3_data.get("object", {})

        # Handle MinIO direct format
        if not object_info and "Key" in record:
            object_key = record.get("Key", "")
            object_size = record.get("Size", 0)
            bucket_name = record.get("Bucket", "")
        else:
            object_key = object_info.get("key", "")
            object_size = object_info.get("size", 0)
            bucket_name = bucket_info.get("name", "")

        if object_key:
            notifications.append(
                WebhookNotification(
                    event_name=event_name,
                    bucket_name=bucket_name,
                    object_key=object_key,
                    object_size=object_size,
                    content_type=object_info.get("contentType", ""),
                )
            )

    return notifications
