"""Small shared helpers for JSON records on disk."""

import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Pydantic model stored on disk with camelCase keys."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


def atomic_write_text(path: Path, text: str) -> None:
    """Write to a temp file in the same folder, then swap it in."""
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
