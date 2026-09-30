"""Daily image limit, counted from today's details.json files."""

from datetime import date
from pathlib import Path

from pydantic import ValidationError

from content_automation.core.jobs import DETAILS_FILE, Job


class DailyLimitError(RuntimeError):
    """The request would exceed IMAGE_DAILY_LIMIT."""


def images_generated_on(output_dir: Path, day: date) -> int:
    """Count output images of completed non-mock jobs in OUTPUT_DIR/<day>/."""
    day_folder = output_dir / day.isoformat()
    if not day_folder.is_dir():
        return 0
    total = 0
    for details in day_folder.glob(f"*/{DETAILS_FILE}"):
        try:
            job = Job.load(details)
        except (OSError, ValueError, ValidationError):
            continue
        if job.status == "completed" and job.provider != "mock":
            total += len(job.outputs)
    return total


def check_daily_limit(
    output_dir: Path, *, limit: int, requested: int, today: date | None = None
) -> int:
    """Raise DailyLimitError if the request does not fit; return images left after it."""
    used = images_generated_on(output_dir, today or date.today())
    if used + requested > limit:
        remaining = max(limit - used, 0)
        raise DailyLimitError(
            f"Daily image limit reached: {used} of {limit} used today, {requested} requested, "
            f"{remaining} left. Raise IMAGE_DAILY_LIMIT or try again tomorrow."
        )
    return limit - used - requested
