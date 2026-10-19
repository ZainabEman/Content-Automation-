"""Roman's Higgsfield jobs for `ca higgsfield` (the CLI never imports a provider module)."""

from content_automation.ai.image.providers.higgsfield_soul import (
    HiggsfieldJob,
    HiggsfieldSoulProvider,
    fail,
    pending_jobs,
    record,
)

__all__ = ["HiggsfieldJob", "HiggsfieldSoulProvider", "fail", "pending_jobs", "record"]
