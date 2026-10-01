"""Higgsfield video clips made by Codex through the Higgsfield MCP server (agent adapter).

The app calls nothing: it writes requests/<stepId>.json (prompt, duration, 9:16, start image,
model and numbered instructions) and returns an awaiting_agent step. Codex uses the connected
Higgsfield MCP's video generation tool, waits for the result, downloads the clip and records
it with `ca job complete`. Exact tool names are confirmed when the MCP is connected
(docs/providers/higgsfield-mcp.md).
"""

from content_automation.ai.video import VideoRequest
from content_automation.core.agent_steps import AgentRequest, create_agent_step
from content_automation.core.config import Settings
from content_automation.core.jobs import AdapterMode, JobStep

MCP_SERVER = "https://mcp.higgsfield.ai/mcp"
MCP_TOOL = "Higgsfield MCP video generation tool (name confirmed when connected)"
_DEFAULT_MODELS = frozenset({"", "mock", "default"})


class HiggsfieldMcpProvider:
    name = "higgsfield-mcp"
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
            f"1. In the connected Higgsfield MCP server, use its video generation tool ({kind}).",
            f"2. Inputs: {inputs}.",
            "3. Check the generation status with the MCP until the video is ready; note the job "
            "ID and the credits it used.",
            "4. Download the finished MP4 to a local folder (for example Downloads).",
            f'5. Run: uv run ca job complete "{job_dir}" --step {step} --file "<downloaded file>" '
            "--provider-job-id <job ID> --credits <credits used>",
            f'6. If it fails, try once more; then run: uv run ca job fail "{job_dir}" '
            f'--step {step} --error "<what happened>"',
            f'7. When every step is recorded: uv run ca video resume "{job_dir}" '
            '(for a content package: uv run ca content build "<package folder>").',
        ]
        return create_agent_step(
            request.job_dir,
            AgentRequest(
                step_id=step,
                capability="video",
                provider=self.name,
                model=model_name,
                mcp_server=MCP_SERVER,
                mcp_tool=MCP_TOOL,
                prompt=request.prompt,
                duration_sec=request.duration_sec,
                aspect_ratio=request.aspect_ratio,
                start_image_path=start,
                start_image_asset_id=request.start_image_asset_id,
                instructions=instructions,
            ),
        )


def create_provider(settings: Settings | None = None) -> HiggsfieldMcpProvider:
    return HiggsfieldMcpProvider()
