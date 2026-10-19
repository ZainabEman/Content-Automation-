"""YouTube research and production planning (PRD v5 R9): `ca youtube …`, skill make-youtube.

Separate from the social workflow (own config/youtube.json, prompts, folders and commands); it
reuses only the shared registry (BG IDs, approve/reject), audit, storage and tracker layers.
Per topic, in outputs/youtube/<YYYY-MM>/<BG-ID>_<slug>/ (R9.11):

    research_<slug>.txt                      (R9.4, checked by `ca youtube check-sources`)
    style-A_investigativ/teleprompter_DE.txt (German only, R9.8)
    style-A_investigativ/script_DE-EN.txt    (generated from the teleprompter file, R9.9)
    style-B_direkte-warnung/…, style-C_menschlich/…
    storyboard_<style folder>.md             (R9.10, after `select style`)
    package.json

The Codex agent researches (web access) and writes the German texts; `ca youtube` makes the
templates, the folders and every free check. Roman records, the editing agency edits; nothing
renders a video.
"""
