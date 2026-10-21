---
name: distribute
description: Prepare approved Branded Genius content for each platform (sizes and per-platform copy) and record what was published. Use for "prepare BG-x for all platforms", "what's ready to publish", "BG-x is live on LinkedIn <url>" and "BG-x failed on TikTok <reason>". No direct publishing: the user posts; published needs the URL.
---

# Distribute

## Rules

- Only an approved review is prepared. There are no publishing integrations (config/publishing.json): the user posts by hand.
- Never mark anything published without the live post's URL from the user; a failure needs their reason.
- Per-platform copy follows write-script's rules (only the template's claims, numbers need verified fact claims) and german-editorial references/platforms.md (the platform's rules).

## Steps

1. "prepare BG-x for all platforms" → `uv run ca prepare BG-x` (or `--platforms linkedin,facebook`): resized variants per platform (config/platforms.json) in `versions/v<n>/platforms/<platform>/`; they upload after the approval.
2. Per platform: `uv run ca copy template BG-x --platform <p> --json`, write the copy from the claims, save a draft and `uv run ca copy save BG-x <draft> --platform <p>`; fix "Not saved" problems. When the variant and copy exist, the platform is "ready to publish".
3. "what's ready to publish" → `uv run ca publish list --ready`.
4. "BG-x is live on LinkedIn <url>" → `uv run ca publish mark BG-x --platform linkedin --url <url>`.
5. "BG-x failed on TikTok <reason>" → `uv run ca publish fail BG-x "<reason>" --platform tiktok`.
