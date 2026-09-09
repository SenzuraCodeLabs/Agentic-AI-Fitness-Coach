"""Weekly digest email job.

Scheduled with APScheduler inside the gateway process. That is adequate for a
single-instance coursework deployment; with several gateway replicas each would
run its own scheduler and users would get duplicate emails, so a production
deployment would need a leader election or a dedicated worker. Documented here
rather than discovered later.

The opt-out flag is checked in the database query itself, not in application
code after fetching. A filter that lives in the query cannot be skipped by a
later code path that forgets to check it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from services.agent3_coach.overload import (
    SessionRecord,
    compute_recommendation,
    compute_tonnage,
    find_personal_records,
)
from services.gateway.email import send_weekly_digest
from shared.db import USERS, WORKOUTS, get_db
from shared.logging import get_logger, new_correlation_id, set_correlation_id

log = get_logger("gateway.digest")


async def build_digest(user_id: str) -> dict[str, Any] | None:
    """Summarise one user's last seven days. None when there is nothing to say."""
    db = get_db()
    since = datetime.now(UTC) - timedelta(days=7)

    cursor = db[WORKOUTS].find({"user_id": user_id, "session_date": {"$gte": since}})
    records: list[SessionRecord] = []
    session_count = 0

    async for document in cursor:
        session_count += 1
        session_date = document.get("session_date") or datetime.now(UTC)
        if session_date.tzinfo is None:
            session_date = session_date.replace(tzinfo=UTC)
        for entry in document.get("sets", []):
            records.append(
                SessionRecord(
                    exercise=entry.get("exercise", "unknown"),
                    load_kg=entry.get("load_kg"),
                    reps=entry.get("reps"),
                    sets=entry.get("sets"),
                    rpe=entry.get("rpe"),
                    session_date=session_date,
                )
            )

    # Nothing trained means nothing worth an email. Sending "you did nothing"
    # weekly is how a digest becomes spam.
    if not records:
        return None

    personal_records = find_personal_records(records)
    pr_lines = [
        f"{exercise}: {data['load_kg']}kg x {data['reps']} "
        f"(estimated 1RM {data['estimated_1rm']}kg)"
        for exercise, data in personal_records.items()
    ]

    targets: list[str] = []
    for exercise in {r.exercise for r in records}:
        history = [r for r in records if r.exercise == exercise]
        recommendation = compute_recommendation(history)
        if recommendation.target_load_kg is not None:
            targets.append(
                f"{exercise}: {recommendation.target_load_kg}kg "
                f"x {recommendation.target_reps} ({recommendation.action.replace('_', ' ')})"
            )

    return {
        "tonnage_kg": compute_tonnage(records),
        "sessions": session_count,
        "prs": pr_lines,
        "targets": targets,
    }


async def send_weekly_digests() -> dict[str, int]:
    """Send the digest to every opted-in, verified user."""
    set_correlation_id(new_correlation_id())
    db = get_db()

    sent = 0
    skipped = 0
    failed = 0

    # The opt-out and verification filters are part of the query. A user who
    # turned digests off is never fetched, so no later code path can email them
    # by mistake.
    cursor = db[USERS].find(
        {"weekly_digest": True, "email_verified": True, "disabled": {"$ne": True}},
        {"_id": 1, "email": 1},
    )

    async for user in cursor:
        digest = await build_digest(user["_id"])
        if digest is None:
            skipped += 1
            continue

        ok = await send_weekly_digest(
            user["email"],
            tonnage_kg=digest["tonnage_kg"],
            sessions=digest["sessions"],
            prs=digest["prs"],
            targets=digest["targets"],
        )
        if ok:
            sent += 1
        else:
            failed += 1

    log.info("weekly_digest_run", sent=sent, skipped=skipped, failed=failed)
    return {"sent": sent, "skipped": skipped, "failed": failed}


def start_scheduler() -> Any:
    """Start the weekly job. Returns the scheduler so it can be shut down."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        send_weekly_digests,
        # Monday morning: a week's summary is most useful before the next week
        # is planned rather than after it has started.
        CronTrigger(day_of_week="mon", hour=7, minute=0),
        id="weekly_digest",
        # If the process was down at the scheduled time, run once on restart
        # rather than firing every missed occurrence.
        coalesce=True,
        misfire_grace_time=3600,
        replace_existing=True,
    )
    scheduler.start()
    log.info("digest_scheduler_started", schedule="Mon 07:00 UTC")
    return scheduler
