"""Dispatch queue supporting online (send now) and offline (queue for later)
modes.

* enqueue_dispatch() always records a DispatchJob. In online mode it attempts
  delivery immediately; failures stay QUEUED for the background worker.
* process_queue() is invoked periodically (FastAPI background task) and
  retries QUEUED/FAILED jobs — this is what drains the queue when
  connectivity returns after offline operation.
* Anomaly checks run before enqueueing; a DispatchBlocked error carries the
  full anomaly list so the UI can display per-record notifications. Passing
  override_reason logs an OverrideLog row and proceeds.
"""
import json
from datetime import datetime

from sqlalchemy.orm import Session

from ...models.entities import (
    Certificate,
    CertStatus,
    DispatchChannel,
    DispatchJob,
    DispatchStatus,
    OverrideLog,
)
from ..certificate_generator import get_org_settings
from ..validation import check_certificate
from .email_sender import send_certificate_email
from .whatsapp_sender import send_certificate_whatsapp

MAX_ATTEMPTS = 5


class DispatchBlocked(Exception):
    def __init__(self, anomalies):
        self.anomalies = anomalies
        super().__init__("Dispatch blocked by anomaly checks")


def enqueue_dispatch(
    db: Session,
    cert: Certificate,
    channel: DispatchChannel,
    recipients: list[str],
    override_reason: str | None = None,
    user: str | None = None,
) -> list[DispatchJob]:
    org = get_org_settings(db)
    anomalies = check_certificate(db, cert, org)
    if anomalies:
        if not override_reason:
            raise DispatchBlocked(anomalies)
        db.add(OverrideLog(
            certificate_id=cert.id,
            anomalies=json.dumps([a.code for a in anomalies]),
            reason=override_reason,
            user=user,
        ))

    jobs = []
    for r in recipients:
        job = DispatchJob(certificate_id=cert.id, channel=channel, recipient=r)
        db.add(job)
        jobs.append(job)
    db.commit()

    if org.dispatch_mode == "online":
        for job in jobs:
            _attempt(db, job, org)
        db.commit()
    return jobs


def _attempt(db: Session, job: DispatchJob, org) -> None:
    job.status = DispatchStatus.SENDING
    job.attempts += 1
    try:
        cert = db.get(Certificate, job.certificate_id)
        if job.channel == DispatchChannel.EMAIL:
            send_certificate_email(org, cert, job.recipient)
        else:
            send_certificate_whatsapp(org, cert, job.recipient)
        job.status = DispatchStatus.SENT
        job.sent_at = datetime.utcnow()
        cert.status = CertStatus.SENT
    except Exception as exc:  # noqa: BLE001 — any transport error requeues
        job.last_error = str(exc)[:2000]
        job.status = (
            DispatchStatus.FAILED if job.attempts >= MAX_ATTEMPTS
            else DispatchStatus.QUEUED
        )


def process_queue(db: Session, limit: int = 50) -> int:
    """Retry queued jobs. Called by the background worker; safe to call
    manually via POST /dispatch/process (e.g. right after connectivity
    returns)."""
    org = get_org_settings(db)
    jobs = (
        db.query(DispatchJob)
        .filter(DispatchJob.status == DispatchStatus.QUEUED)
        .order_by(DispatchJob.created_at)
        .limit(limit)
        .all()
    )
    for job in jobs:
        _attempt(db, job, org)
    db.commit()
    return len(jobs)
