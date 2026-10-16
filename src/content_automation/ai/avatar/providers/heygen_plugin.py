"""HeyGen avatar clips made by Codex with the HeyGen plugin (agent adapter).

The app calls nothing: it writes requests/<stepId>.json (script, avatar, voice, aspect,
numbered instructions) and returns an awaiting_agent step. Codex finds the HeyGen plugin's
avatar video tool at run time (no tool name is assumed), shows the user the cost, makes the
clip with the person's own avatar and the chosen voice, saves it and records it with
`ca job complete` (or `ca job fail`; no retries). The make-video skill describes the full
exchange. The voice is always passed explicitly: an avatar without a default voice is
rejected by HeyGen, and a default voice may not be his.
"""

from content_automation.ai.avatar import AvatarProviderError, AvatarRequest
from content_automation.core.agent_steps import AgentRequest, create_agent_step
from content_automation.core.config import Settings
from content_automation.core.jobs import AdapterMode, JobStep

PLUGIN = "HeyGen"
PERSON_RULE = (
    "The avatar must be the identity person's own avatar (made from his own photos or video). "
    "Never use a stock avatar or a different person."
)
_DEFAULT_MODELS = frozenset({"", "mock", "default"})


class HeygenPluginProvider:
    name = "heygen-plugin"
    mode: AdapterMode = "agent"

    def __init__(
        self, default_avatar_id: str | None = None, default_voice_id: str | None = None
    ) -> None:
        self._default_avatar_id = default_avatar_id
        self._default_voice_id = default_voice_id

    def generate(self, request: AvatarRequest, model: str) -> JobStep:
        job_dir = request.job_dir.resolve()
        step = request.step_id
        avatar = request.avatar_id or self._default_avatar_id
        voice = request.voice_id or self._default_voice_id
        if not avatar or not voice:  # the video job checks this before the job exists
            missing = [name for name, value in (("HEYGEN_AVATAR_ID", avatar),
                                                ("HEYGEN_VOICE_ID", voice)) if not value]
            raise AvatarProviderError(f"{', '.join(missing)} not set in .env.")
        instructions = [
            f"1. Use the {PLUGIN} plugin in Codex: find its avatar video tool among the plugin's "
            "tools now; do not assume a tool name. If the plugin is not available, stop and tell "
            f"the user that the {PLUGIN} plugin is missing.",
            f"2. Inputs: script = the prompt above, spoken word for word; avatar = {avatar}; "
            f"voice = {voice} (pass this voice ID explicitly in every request; never leave the "
            f"voice out or rely on the avatar's default voice); aspect ratio "
            f"{request.aspect_ratio}; "
            f"about {request.duration_sec:g} s.",
            f"3. Person: {PERSON_RULE}",
            "4. Before generating, show the user the script, the provider, the avatar, the voice, "
            'the duration and any credit cost the plugin reports, and wait for "ok".',
            "5. Wait until the video is ready; note its video ID and the credits it used.",
            "6. Save the MP4 locally (for a content package: in its video/clips/ folder).",
            f'7. Run: uv run ca job complete "{job_dir}" --step {step} --file "<saved file>" '
            "--provider-job-id <video ID> --credits <credits used>",
            f'8. If it fails, do not retry: uv run ca job fail "{job_dir}" --step {step} '
            '--error "<the reason>"',
            f'9. When every step is recorded: uv run ca video resume "{job_dir}" '
            '(for a content package: uv run ca content build "<package folder>").',
        ]
        return create_agent_step(
            request.job_dir,
            AgentRequest(
                step_id=step,
                capability="avatar",
                provider=self.name,
                model="the tool's default" if model in _DEFAULT_MODELS else model,
                plugin=PLUGIN,
                prompt=request.script,
                duration_sec=request.duration_sec,
                aspect_ratio=request.aspect_ratio,
                person_rule=PERSON_RULE,
                options={"avatarId": avatar, "voiceId": voice},
                instructions=instructions,
            ),
        )


def create_provider(settings: Settings | None = None) -> HeygenPluginProvider:
    if settings is None:
        return HeygenPluginProvider()
    return HeygenPluginProvider(settings.heygen_avatar_id, settings.heygen_voice_id)
