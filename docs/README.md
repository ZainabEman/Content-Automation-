# Content Automation

This project is a local foundation for three traceable content workflows: image generation, video and voice, and research-to-content packaging. The modules are planned in the PRDs and are not implemented by this foundation task.

## Run locally

1. Install uv using the [official installer](https://docs.astral.sh/uv/getting-started/installation/).
2. From the project folder, run `uv sync`.
3. Run `uv run ca hello` to see a safe configuration summary.

The Python version is pinned to 3.13. Copy `../.env.example` to `.env` only if you need to restore the local environment file; keep real credentials in `.env` and never share them.

## Project plans

- [Module 1: Core and Image Branch](prd/module-1.md)
- [Module 2: Video and Voice Branch](prd/module-2.md)
- [Module 3: Research and Full Pipeline](prd/module-3.md)
- [Technical blueprint](blueprints/blueprint.md)
- [Progress log](PROGRESS.md)

## Guides

- [Guide template](guides/_TEMPLATE.md)
- [Module 1: Images](guides/module-1-images.md)
- [Module 2: Video](guides/module-2-video.md)
- [Module 3: Research](guides/module-3-research.md)

Module guides are written as each module is implemented.
