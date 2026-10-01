"""HeyGen avatar clips made by Codex through the HeyGen MCP server (agent adapter).

The app calls nothing: it writes requests/<stepId>.json (script, avatar, 9:16, numbered
instructions) and returns an awaiting_agent step. Codex uses the connected HeyGen MCP's
avatar video tool, waits for the result, downloads the clip and records it with
`ca job complete`. Exact tool names are confirmed when the MCP is connected
(docs/providers/heygen-mcp.md).
"""

from content_automation.ai.avatar import AvatarRequest
from content_automation.core.agent_steps import AgentRequest, create_agent_step
from content_automation.core.config import Settings
from content_automation.core.jobs import AdapterMode, JobStep

MCP_SERVER = "https://mcp.heygen.com/mcp/v1/"
MCP_TOOL = "HeyGen MCP avatar video tool (name confirmed when connected)"
_DEFAULT_MODELS = frozenset({"", "mock", "default"})


class HeygenMcpProvider:
    name = "heygen-mcp"
    mode: AdapterMode = "agent"

    def __init__(self, default_avatar_id: str | None = None) -> None:
        self._default_avatar_id = default_avatar_id

    def generate(self, request: AvatarRequest, model: str) -> JobStep:
        job_dir = request.job_dir.resolve()
        step = request.step_id
        avatar = request.avatar_id or self._default_avatar_id
        avatar_text = avatar or (
            "not set: list the avatars with the HeyGen MCP, ask the user which one to use, "
            "and ask them to put its ID in .env as HEYGEN_AVATAR_ID"
        )
        instructions = [
            "1. In the connected HeyGen MCP server, use its avatar video generation tool.",
            f"2. Inputs: script = the prompt above, spoken word for word; avatar = {avatar_text}; "
            f"voice = the avatar's default voice; portrait {request.aspect_ratio}; "
            f"about {request.duration_sec:g} s.",
            "3. Check the video status with the MCP until it is ready; note the video ID and "
            "the credits it used.",
            "4. Download the finished MP4 to a local folder (for example Downloads).",
            f'5. Run: uv run ca job complete "{job_dir}" --step {step} --file "<downloaded file>" '
            "--provider-job-id <video ID> --credits <credits used>",
            f'6. If it fails, try once more; then run: uv run ca job fail "{job_dir}" '
            f'--step {step} --error "<what happened>"',
            f'7. When every step is recorded: uv run ca video resume "{job_dir}" '
            '(for a content package: uv run ca content build "<package folder>").',
        ]
        return create_agent_step(
            request.job_dir,
            AgentRequest(
                step_id=step,
                capability="avatar",
                provider=self.name,
                model="the tool's default" if model in _DEFAULT_MODELS else model,
                mcp_server=MCP_SERVER,
                mcp_tool=MCP_TOOL,
                prompt=request.script,
                duration_sec=request.duration_sec,
                aspect_ratio=request.aspect_ratio,
                options={"avatarId": avatar or "", "voice": "avatar default"},
                instructions=instructions,
            ),
        )


def create_provider(settings: Settings | None = None) -> HeygenMcpProvider:
    return HeygenMcpProvider(settings.heygen_avatar_id if settings else None)
