from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

from agentguard.config import get_settings
from agentguard.repository import PostgresRepository, StaleLeaseError
from agentguard.secureguard import SecureGuard

logger = logging.getLogger(__name__)


async def work() -> None:
    settings = get_settings()
    repository = await PostgresRepository.connect(settings.database_url, settings.max_job_attempts)
    await repository.migrate()
    secureguard = SecureGuard()
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopping.set)

    logger.info("SecureGuard worker %s started", settings.worker_id)
    try:
        while not stopping.is_set():
            job = await repository.claim_job(settings.worker_id, settings.lease_seconds)
            if job is None:
                with suppress(TimeoutError):
                    await asyncio.wait_for(stopping.wait(), timeout=settings.poll_interval_seconds)
                continue

            try:
                result = await secureguard.execute(job)
                await repository.complete_job(job, settings.worker_id, result)
                logger.info("completed job=%s request=%s", job.id, job.request_id)
            except StaleLeaseError:
                logger.warning("discarded stale result for job=%s", job.id)
            except Exception as exc:
                terminal = await repository.fail_job(job, settings.worker_id, str(exc))
                logger.exception("job=%s failed terminal=%s", job.id, terminal)
    finally:
        await repository.close()


def run() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(work())
