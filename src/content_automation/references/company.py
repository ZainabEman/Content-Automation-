"""Company profile read from docs/company/services.md (COMPANY_FILE).

The file is plain Markdown for people: a "# <Name> — ..." heading, a summary paragraph,
"Label: text" lines (Positioning, Core message, Content rules, ...) and a numbered
service list. The prompt builder uses the name, summary, core message and content rules.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

_LABEL = re.compile(r"^([A-Za-z][A-Za-z ]{1,30}):(?:\s+(.*))?$")
_SERVICE = re.compile(r"^\d+\.\s+(.+)$")


@dataclass(frozen=True)
class CompanyProfile:
    name: str
    summary: str
    fields: dict[str, str] = field(default_factory=dict)  # "Core message" -> text
    services: list[str] = field(default_factory=list)  # full service lines

    @property
    def core_message(self) -> str:
        return self.fields.get("Core message", "")

    @property
    def content_rules(self) -> str:
        return self.fields.get("Content rules", "")

    @property
    def website(self) -> str:
        """Optional "Website: https://..." line; pre-fills the caption link of a brief."""
        return self.fields.get("Website", "")


def load_company(path: Path) -> CompanyProfile | None:
    """Parse the company file; None when it does not exist."""
    if not path.is_file():
        return None
    name, summary = "", ""
    fields: dict[str, str] = {}
    services: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# ") and not name:
            name = re.split(r"\s+[—-]\s+", line[2:], maxsplit=1)[0].strip()
        elif match := _SERVICE.match(line):
            services.append(match.group(1))
        elif match := _LABEL.match(line):
            if match.group(2):
                # "website: ..." and "Website: ..." are the same label.
                fields[match.group(1).strip().capitalize()] = match.group(2)
        elif not line.startswith("#") and not summary:
            summary = line
    return CompanyProfile(name=name, summary=summary, fields=fields, services=services)


def first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
