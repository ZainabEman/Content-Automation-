"""PRD v5 end-to-end check, offline on mocks (§7: criteria 1, 4, 5, 6, 7, 9, 11, 12).

Run:  uv run python scripts/e2e_v5.py [--keep]

In a temp folder (the Phase 4 sandbox: a copy of config/, stand-in references and logo, mock
image, scraper and storage providers): one month of social planning (`ca plan month`), one
package per category built with the mock image provider (LinkedIn post, Facebook post, Facebook
ad, Instagram carousel: German brief, dry run, "ok" as --authorize, build, design check), then
the German check over every text a reader sees (briefs and the drawn designs), the category
rules on the rendered manifests, and one YouTube topic package (scripts/youtube_mock_package.py,
fixture pages). No network, no paid call.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

REPO = Path(__file__).resolve().parents[1]
TOPICS = {
    "linkedin_post": "KI-Chatbots beantworten Patientenfragen nach Praxisschluss",
    "facebook_post": "KI-Chatbots für Zahnarztpraxen",
    "facebook_ad": "KI-Chatbot bucht Termine per WhatsApp",
    "instagram_carousel": "So startet Ihre Praxis mit einem KI-Chatbot",
}
HASHTAGS = ["#BrandedGenius", "#KI", "#Chatbots"]


def _module(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _samples() -> dict[str, dict[str, Any]]:
    data: dict[str, dict[str, Any]] = json.loads(
        (REPO / "config" / "design_preview_copy.json").read_text(encoding="utf-8"))
    return data


def _variant_copy(direction: str, layout: str, template: dict[str, Any],
                  illustration: str) -> dict[str, Any]:
    sample = dict(_samples()[f"{direction}/{layout}"])
    filled = {name: sample.get(name, value) for name, value in template.items()}
    if "illustration" in template:
        filled["illustration"] = illustration
    return filled


def fill_brief(template_file: Path, deliverable: str, e2e4: ModuleType) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(template_file.read_text(encoding="utf-8"))
    brief = {key: value for key, value in data.items() if key != "_help"}
    ids = brief["sourceArticleIds"]
    brief.update({
        "service": "AI chatbots",
        "objective": "Praxen zeigen, wie ein Chatbot nach Feierabend Termine bucht",
        "keyPoints": ["Beantwortet Fragen nachts", "Bucht freie Termine per SMS",
                      "Übergibt offene Fälle an den Empfang"],
        "insights": [{"text": text, "source": ids[i % len(ids)]}
                     for i, text in enumerate(e2e4.INSIGHTS)],
        "cta": ("Fordern Sie Ihre kostenfreie KI-Potenzialanalyse an: Wir zeigen Ihnen, wie "
                "ein Praxis-Chatbot Ihre Patienten per WhatsApp berät, Termine bucht und "
                "rechtzeitig vor dem Besuch erinnert."),
        "hashtags": HASHTAGS,
    })
    illustration = e2e4.ILLUSTRATION
    for part in ("post", "ad"):
        slot = brief.get(part)
        if isinstance(slot, dict) and slot.get("direction"):
            slot["copy"] = _variant_copy(slot["direction"], "post", slot["copy"], illustration)
            slot["altText"] = ("Grafik mit einer Überschrift zum Praxis-Chatbot und einem Bild "
                               "zum Thema")
    if isinstance(brief.get("ad"), dict) and brief["ad"].get("direction"):
        brief["ad"]["adFields"] = {
            "primaryText": "Ihr Vertrieb schläft. Unser KI-Chatbot beantwortet Anfragen per "
                           "WhatsApp rund um die Uhr und bucht freie Termine.",
            "headline": "KI-Chatbot für Ihre Praxis", "description": "Kostenfrei testen",
            "ctaButton": "Learn more"}
    carousel = brief.get("carousel")
    if isinstance(carousel, dict) and carousel.get("direction"):
        for slide in carousel["slides"]:
            layout = {"cover": "cover", "point": "point", "cta": "cta"}[slide["directionRole"]]
            slide["copy"] = _variant_copy(carousel["direction"], layout, slide["copy"],
                                          illustration)
            slide["altText"] = "Folie zum Praxis-Chatbot mit Überschrift und Bild"
    for caption in brief["captions"].values():
        caption.update({"hook": "Die meisten Patienten, die Ihrer Praxis nach 18:00 Uhr "
                                "schreiben, buchen woanders, bevor sie eine Antwort bekommen.",
                        "takeaways": e2e4.TAKEAWAYS[:5],
                        "question": "Welche Fragen stellen Ihre Patienten nach Praxisschluss "
                                    "am häufigsten, und wer beantwortet sie heute?"})
    (template_file.parent / "brief.json").write_text(json.dumps(brief, indent=2,
                                                                ensure_ascii=False),
                                                     encoding="utf-8")
    return brief


def build(deliverable: str, work: Path, e2e4: ModuleType, notes: dict[str, list[str]]
          ) -> Path | None:
    before = set((work / "outputs" / "content").glob("*")) if (
        work / "outputs" / "content").exists() else set()
    code, out, err = e2e4._ca("content", "start", "--topic", TOPICS[deliverable],
                              "--deliverables", deliverable)
    if code != 0:
        notes["errors"].append(f"{deliverable} start: {err.strip()[-200:]}")
        return None
    folder = next(iter(set((work / "outputs" / "content").glob("*")) - before))
    notes["variants"].append(next((line for line in out.splitlines()
                                   if line.startswith("Layout variant:")), "?"))
    fill_brief(folder / "brief.template.json", deliverable, e2e4)
    code, out, err = e2e4._ca("content", "build", str(folder), "--dry-run")
    ids = re.findall(r"Dry run ID: (DR-\S+)", out)
    if code != 0 or not ids:
        notes["errors"].append(f"{deliverable} dry run: {(out + err).strip()[-400:]}")
        return None
    code, out, err = e2e4._ca("content", "build", str(folder), "--authorize", ids[0])
    for _ in range(8):  # the carousel's set check: the agent compares, here: recorded as pass
        reviews = re.findall(r'uv run ca job review "([^"]+)" --check set --image (\S+) --pass',
                             out)
        if not reviews:
            break
        for job_folder, image in reviews:
            e2e4._ca("job", "review", job_folder, "--check", "set", "--image", image, "--pass",
                     "--note", "e2e: same fonts, colours and layout family")
        code, out, err = e2e4._ca("content", "build", str(folder))
    package = json.loads((folder / "package.json").read_text(encoding="utf-8"))
    if code != 0 or package.get("status") not in ("draft", "done", "upload_pending"):
        notes["errors"].append(f"{deliverable} build ({package.get('status')}): "
                               f"{(out + err).strip()[-400:]}")
        return None
    return folder


def manifests(work: Path, folder: Path) -> list[dict[str, Any]]:
    """The render manifests of a package's images (job folders of this package)."""
    found = []
    for path in sorted((work / "outputs" / "jobs").rglob("*.design.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        details = path.parent / "details.json"
        text = details.read_text(encoding="utf-8") if details.exists() else ""
        if folder.name in text:
            found.append(data)
    return found


def run(keep: bool = False) -> list[tuple[str, bool, str]]:
    sys.path.insert(0, str(REPO / "src"))
    from content_automation.content.brief import ContentBrief
    from content_automation.content.german import check_texts
    from content_automation.content.quality import reader_texts

    e2e4 = _module("e2e_phase4")
    results: list[tuple[str, bool, str]] = []
    notes: dict[str, list[str]] = {"errors": [], "variants": []}
    with e2e4._sandbox(keep) as work:
        e2e4._setup(work)
        code, out, err = e2e4._ca("plan", "month", "2026-11")
        planned = json.loads((work / "calendar" / "2026-11-month-plan.json").read_text(
            encoding="utf-8"))["assets"] if code == 0 else []
        results.append(("§7.9 the monthly planner: 30-60 assets with a format mix",
                        code == 0 and 30 <= len(planned) <= 60
                        and len({a["deliverable"] for a in planned}) == 4,
                        f"{len(planned)} assets"))
        results.append(("§7.7 no platform has three near-identical images in a row",
                        "no platform has three near-identical images" in out, ""))
        built = {name: build(name, work, e2e4, notes) for name in TOPICS}
        results.append(("one item per category built on mock (design check passed)",
                         all(built.values()), "; ".join(notes["errors"])[:600]))
        german_errors: list[str] = []
        all_manifests: dict[str, list[dict[str, Any]]] = {}
        for name, folder in built.items():
            if folder is None:
                continue
            raw = json.loads((folder / "brief.json").read_text(encoding="utf-8"))
            brief = ContentBrief.model_validate(raw)
            german_errors += check_texts(reader_texts(brief)).errors
            all_manifests[name] = manifests(work, folder)
            drawn = [(f"{name} {t['zone']}", t["text"]) for m in all_manifests[name]
                     for t in m["texts"] if t["zone"] != "footer"]
            german_errors += check_texts(drawn).errors
        carousel = all_manifests.get("instagram_carousel", [])
        last = carousel[-1] if carousel else {}
        rule4 = (5 <= len(carousel) <= 6 and all(not m["logo"] for m in carousel[:-1])
                 and bool(last.get("logo")) and all(not m["footer"] for m in carousel[:-1])
                 and not any(re.search(r"\b\d{1,2}\s*/\s*\d{1,2}\b", t["text"])
                             for m in carousel for t in m["texts"]))
        results.append(("§7.4 carousel: 5-6 slides, no counter, logo (and website) only on "
                        "the last slide", rule4, f"{len(carousel)} slides"))
        linkedin = all_manifests.get("linkedin_post", [])
        rule6 = bool(linkedin) and all(
            m["size"] == [1080, 1440] and m["logo"] and (
                m["logo"]["box"][0] <= 216 or m["logo"]["box"][2] >= 864) for m in linkedin)
        results.append(("§7.6 LinkedIn 3:4 with the official logo at a side corner "
                        "(hash checked by the design check)", rule6, ""))
        post, ad = built.get("facebook_post"), built.get("facebook_ad")
        separate = bool(post and ad) and post != ad
        if post and ad:
            separate = separate and json.loads((post / "package.json").read_text(
                encoding="utf-8"))["category"] == "facebook_post" and json.loads(
                (ad / "package.json").read_text(encoding="utf-8"))["category"] == "facebook_ad"
        results.append(("§7.5 Facebook posts and ads: separate variants, packages, folders",
                         separate, ""))
        yt = _module("youtube_mock_package")
    result = yt.run(copy_to=None)  # its own sandbox; the teleprompter check is the German pass
    youtube_ok = all(code == 0 for name, code in result["steps"].items() if name != "blocked")
    results.append(("§7.11 one YouTube topic: research, 3 styles x 2 files, storyboard (R9.11)",
                    youtube_ok and sum(path.endswith(("teleprompter_DE.txt", "script_DE-EN.txt"))
                                       for path in result["files"]) == 6
                    and any(path.startswith("storyboard_") for path in result["files"]),
                    ", ".join(f"{k} {v}" for k, v in result["steps"].items())))
    results.append(("§7.12 the source check catches a dead URL and a misquote",
                    "HTTP 404" in result["failedCheck"]["output"]
                    and "NOT FOUND in S1" in result["failedCheck"]["output"], ""))
    results.append(("§7.1 no audience-facing English in the social and YouTube outputs "
                    "(German check)", not german_errors
                    and "PASS" in result.get("checkOutput", ""),
                    "; ".join(german_errors[:5])))
    return results


def main() -> int:
    results = run(keep="--keep" in sys.argv)
    for text, passed, note in results:
        print(f"{'PASS' if passed else 'FAIL'} {text}" + (f" ({note})" if note else ""))
    passed = sum(ok for _, ok, _ in results)
    print(f"{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
