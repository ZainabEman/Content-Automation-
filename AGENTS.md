# Working rules

- Stack: Python 3.13, uv, Typer, Pydantic, pytest, mypy strict, and Ruff. Run project commands with `uv run`.
- Background architecture: `docs/blueprints/blueprint.md`; read it only when needed. Do not touch `imagegen/`.
- Before each task, read `docs/PROGRESS.md` and that task's PRD; inspect the code first, do only that task, keep working code, and avoid big rewrites.
- Providers: each capability has one public interface in its entry package (`content_automation/ai/<cap>/__init__.py`; scraper: `content_automation/research/collectors/__init__.py`).
- Put one adapter module per provider under that capability's `providers/`; choose with `<CAP>_PROVIDER` and `<CAP>_MODEL`, and always provide a mock adapter.
- App code imports capability entry packages only; a test enforces this boundary. A new provider takes one adapter file and two environment changes.
- Images: `generate_image()` lives in `content_automation.ai.image`; adapters are mock and Gemini, selected by `IMAGE_PROVIDER` and `IMAGE_MODEL`.
- Adapter modes are `code` (the app calls the API) and `agent` (Codex calls the MCP tool; the app records it through job commands).
- Keep keys only in `.env`. Never print, log, commit, or put keys in docs or prompts; never ask for keys in chat.
- Every job writes `details.json`; never mark a job completed without its output file, and record failures with the error.
- Tests run offline with mocks. Credit-spending calls require a task explicitly marked LIVE and an estimate stated first.
- Each task updates `docs/guides/module-N-<name>.md` from `docs/guides/_TEMPLATE.md` in plain language for non-coders; `docs/README.md` links every guide.
- Finish each task: `uv run pytest`, `uv run mypy src`, and `uv run ruff check` pass; add one line to `docs/PROGRESS.md`; commit as `M<n>.T<n>: <title>`; reply in at most five lines with changes, tests, blockers, and what the user must do.

## Playbooks

### Make images

### Make videos

### Research

### Idea to package
