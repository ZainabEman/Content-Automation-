"""Higgsfield video clips made by Codex with the Higgsfield plugin (agent adapter).

The app calls nothing: it writes requests/<stepId>.json (prompt, duration, 9:16, start image,
identity photos, model and numbered instructions) and returns an awaiting_agent step. Codex
finds the Higgsfield plugin's video tool at run time (no tool name is assumed), shows the
user the cost, makes the clip, saves it and records it with `ca job complete` (or
`ca job fail`; no retries). The make-video skill describes the full exchange.
"""

from content_automation.ai.video import VideoRequest
from content_automation.core.agent_steps import AgentRequest, create_agent_step
from content_automation.core.config import Settings
from content_automation.core.jobs import AdapterMode, JobStep

PLUGIN = "Higgsfield"
PERSON_RULE = (
    "Any person in this clip must be the man in identityImages: pass those photos as "
    "reference images if the tool accepts images. If it cannot take reference images and the "
    "shot needs a person, stop and ask the user. Shots without him show no people, faces or "
    "human figures. Never generate a different person and never describe his face in words."
)
_DEFAULT_MODELS = frozenset({"", "mock", "default"})


class HiggsfieldPluginProvider:
    name = "higgsfield-plugin"
    mode: AdapterMode = "agent"

    def generate(self, request: VideoRequest, model: str) -> JobStep:
        job_dir = request.job_dir.resolve()
        step = request.step_id
        model_name = "the tool's default model" if model in _DEFAULT_MODELS else model
        start = str(request.start_image_path.resolve()) if request.start_image_path else None
        kind = "image-to-video, starting from the start image" if start else "text-to-video"
        inputs = (
            f"prompt = the prompt above; duration = {request.duration_sec:g} s (max 15); "
            f"aspect ratio = {request.aspect_ratio}; model = {model_name}"
        )
        if start:
            inputs += f"; start image = {start} (upload it first if the tool needs a URL)"
        instructions = [
            f"1. Use the {PLUGIN} plugin in Codex: find its video generation tool ({kind}) among "
            "the plugin's tools now; do not assume a tool name. If the plugin is not available, "
            f"stop and tell the user that the {PLUGIN} plugin is missing.",
            f"2. Inputs: {inputs}.",
            f"3. Person: {PERSON_RULE}",
            "4. Before generating, show the user the prompt, the provider and any credit cost the "
            'plugin reports, and wait for "ok".',
            "5. Wait until the video is ready; note its job ID and the credits it used.",
            "6. Save the MP4 locally (for a content package: in its video/clips/ folder).",
            f'7. Run: uv run ca job complete "{job_dir}" --step {step} --file "<saved file>" '
            "--provider-job-id <job ID> --credits <credits used>",
            f'8. If it fails, do not retry: uv run ca job fail "{job_dir}" --step {step} '
            '--error "<the reason>"',
            f'9. When every step is recorded: uv run ca video resume "{job_dir}" '
            '(for a content package: uv run ca content build "<package folder>").',
        ]
        return create_agent_step(
            request.job_dir,
            AgentRequest(
                step_id=step,
                capability="video",
                provider=self.name,
                model=model_name,
                plugin=PLUGIN,
                prompt=request.prompt,
                duration_sec=request.duration_sec,
                aspect_ratio=request.aspect_ratio,
                start_image_path=start,
                start_image_asset_id=request.start_image_asset_id,
                identity_images=[str(path.resolve()) for path in request.identity_image_paths],
                person_rule=PERSON_RULE,
                instructions=instructions,
            ),
        )


def create_provider(settings: Settings | None = None) -> HiggsfieldPluginProvider:
    return HiggsfieldPluginProvider()
