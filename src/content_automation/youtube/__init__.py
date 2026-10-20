"""YouTube research and production planning (PRD v5 R9): `ca youtube …`, skill make-youtube.

Separate from the social workflow (own config/youtube.json, prompts, folders and commands); it
reuses only the shared registry (BG IDs, approve/reject), audit, storage and tracker layers.
Per topic (PRD v6 R7), in outputs/YouTube Long-Form/<Topic Name>/:

    research.txt                             (R9.4, checked by `ca youtube check-sources`)
    Style A/script_de_teleprompter.txt       (German only, R9.8)
    Style A/script_de_en_bilingual.txt       (generated from the teleprompter file, R9.9)
    Style A/storyboard.txt                   (R9.10, matching that style's script)
    Style B/…, Style C/…

The topic folder is the readable title; the BG ID and the metadata are in
outputs/_system/youtube/<BG-ID>.json (with the internal briefs). A re-run fills in missing files
and never overwrites one: a changed file is written as <name>_v2.txt (then _v3 …).

The Codex agent researches (web access) and writes the German texts; `ca youtube` makes the
templates, the folders and every free check. Roman records, the editing agency edits; nothing
renders a video.
"""
