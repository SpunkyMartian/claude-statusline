# claude-statusline

A custom statusline for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — text-only, no emojis.

![Python](https://img.shields.io/badge/python-3.8+-blue)

## What it shows

**Line 1:** model | working directory | git branch (clickable) +staged ~modified ?untracked | +added/-removed

**Line 2:** context tokens/total % | current rate limit % (resets time) | weekly rate limit % (resets date) | extra usage balance

- Git branch is an OSC 8 hyperlink — Cmd+click (macOS) or Ctrl+click to open the repo on GitHub
- Rate limit percentages are color-coded: green (<70%), yellow (70-89%), red (90%+)
- Context usage is measured against the autocompact threshold (~80% of the full window)

## How it works

- Reads Claude Code's statusline JSON from stdin
- Fetches rate limit data from Anthropic's OAuth usage API (cached for 60s)
- Caches git status for 5s to avoid lag in large repos
- Retrieves OAuth tokens from `~/.claude/.credentials.json` or macOS Keychain

## Setup

Add to your Claude Code settings (`~/.claude/settings.json`):

```json
{
  "statusline": {
    "command": "python3 /path/to/statusline.py"
  }
}
```

## Requirements

- Python 3.8+
- Claude Code with a valid OAuth session (Pro/Max subscription)
- No external dependencies — uses only the Python standard library
