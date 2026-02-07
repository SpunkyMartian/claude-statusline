#!/usr/bin/env python3
"""
Custom Claude Code statusline — text-only, no emojis.

Line 1: model | context tokens/total % | session cost | duration | path
Line 2: 5h: 45% resets 2:30pm | week: 12% resets feb 10 | extra: $2.15/$50.00
Line 3: branch +staged ~modified ?untracked | +added/-removed

Calls Anthropic OAuth usage API directly for rate limits.
Git info cached to avoid lag in large repos.
"""
import json, sys, subprocess, os, time, urllib.request
from datetime import datetime
from pathlib import Path

data = json.load(sys.stdin)

# ── ANSI (no emojis) ──
RESET  = '\033[0m'
DIM    = '\033[2m'
GREEN  = '\033[32m'
YELLOW = '\033[33m'
RED    = '\033[31m'
CYAN   = '\033[36m'
WHITE  = '\033[37m'
SEP    = f" {DIM}|{RESET} "


def fmt_tok(n):
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}k"
    return str(n)


def fmt_reset(iso, style="time"):
    """Convert ISO reset time to compact local time."""
    if not iso:
        return ""
    try:
        utc = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        local = utc.astimezone()
        if style == "time":
            return local.strftime("%-I:%M%p").lower()
        return local.strftime("%b %-d, %-I:%M%p").lower()
    except Exception:
        return ""


def usage_color(pct):
    if pct >= 90: return RED
    if pct >= 70: return YELLOW
    return GREEN


# ── Model ──
model = data.get('model', {}).get('display_name', '?')

# ── Context window ──
ctx      = data.get('context_window', {})
pct      = ctx.get('used_percentage') or 0
pct_int  = int(pct)
total_sz = ctx.get('context_window_size', 200000)
cur      = ctx.get('current_usage') or {}
used_tok = (cur.get('input_tokens') or 0) + \
           (cur.get('cache_creation_input_tokens') or 0) + \
           (cur.get('cache_read_input_tokens') or 0)

# ── Cost & duration ──
cost_obj     = data.get('cost', {})
session_cost = cost_obj.get('total_cost_usd') or 0
duration_ms  = cost_obj.get('total_duration_ms') or 0
lines_add    = cost_obj.get('total_lines_added') or 0
lines_rm     = cost_obj.get('total_lines_removed') or 0
mins = duration_ms // 60000
secs = (duration_ms % 60000) // 1000

# ── Path ──
cwd  = data.get('workspace', {}).get('current_dir') or data.get('cwd', '')
home = os.path.expanduser('~')
path_short = ('~' + cwd[len(home):]) if cwd.startswith(home) else cwd

# ── Usage API (5h, weekly, extra) — cached 60s ──
USAGE_CACHE = '/tmp/claude-statusline-usage-cache.json'
USAGE_MAX_AGE = 60

usage_data = None
try:
    needs_refresh = True
    if os.path.exists(USAGE_CACHE):
        if (time.time() - os.path.getmtime(USAGE_CACHE)) < USAGE_MAX_AGE:
            needs_refresh = False
            with open(USAGE_CACHE) as f:
                usage_data = json.load(f)

    if needs_refresh:
        token = ""
        # Try .credentials.json first (Linux/Windows), then macOS Keychain
        creds_path = Path.home() / ".claude" / ".credentials.json"
        if creds_path.exists():
            creds = json.loads(creds_path.read_text())
            token = creds.get("claudeAiOauth", {}).get("accessToken", "")
        if not token and sys.platform == "darwin":
            try:
                import getpass
                kc_out = subprocess.check_output(
                    ["security", "find-generic-password",
                     "-s", "Claude Code-credentials",
                     "-a", getpass.getuser(), "-w"],
                    text=True, stderr=subprocess.DEVNULL).strip()
                kc_creds = json.loads(kc_out)
                token = kc_creds.get("claudeAiOauth", {}).get("accessToken", "")
            except Exception:
                pass
        if token:
            req = urllib.request.Request(
                "https://api.anthropic.com/api/oauth/usage",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                    "anthropic-beta": "oauth-2025-04-20",
                    "User-Agent": "claude-code/2.1.34",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                usage_data = json.loads(resp.read())
            with open(USAGE_CACHE, 'w') as f:
                json.dump(usage_data, f)
except Exception:
    # Fall back to stale cache
    if os.path.exists(USAGE_CACHE) and usage_data is None:
        try:
            with open(USAGE_CACHE) as f:
                usage_data = json.load(f)
        except Exception:
            pass

# ── Git (cached 5s) ──
GIT_CACHE   = '/tmp/claude-statusline-git-cache'
GIT_MAX_AGE = 5

git_info = ''
try:
    work_dir = data.get('workspace', {}).get('current_dir') or None
    subprocess.check_output(['git', 'rev-parse', '--git-dir'],
                            stderr=subprocess.DEVNULL, cwd=work_dir)

    git_stale = (not os.path.exists(GIT_CACHE)) or \
                (time.time() - os.path.getmtime(GIT_CACHE)) > GIT_MAX_AGE

    if git_stale:
        branch = subprocess.check_output(
            ['git', 'branch', '--show-current'],
            text=True, stderr=subprocess.DEVNULL, cwd=work_dir).strip()
        porcelain = subprocess.check_output(
            ['git', 'status', '--porcelain'],
            text=True, stderr=subprocess.DEVNULL, cwd=work_dir).strip()

        staged = modified = untracked = 0
        for line in porcelain.split('\n'):
            if not line: continue
            idx, wt = line[0], line[1]
            if idx == '?':
                untracked += 1
            else:
                if idx not in (' ', '?'): staged += 1
                if wt not in (' ', '?'): modified += 1

        with open(GIT_CACHE, 'w') as f:
            f.write(f"{branch}|{staged}|{modified}|{untracked}")
    else:
        with open(GIT_CACHE) as f:
            parts = f.read().strip().split('|')
            branch    = parts[0]
            staged    = int(parts[1])
            modified  = int(parts[2])
            untracked = int(parts[3])

    pieces = [branch]
    if staged:    pieces.append(f"{GREEN}+{staged}{RESET}")
    if modified:  pieces.append(f"{YELLOW}~{modified}{RESET}")
    if untracked: pieces.append(f"{DIM}?{untracked}{RESET}")
    git_info = ' '.join(pieces)
except Exception:
    git_info = ''

# ════════════════ OUTPUT ════════════════

# Line 1: model | context | cost | duration | path
ctx_c = usage_color(pct_int)
line1 = SEP.join([
    f"{WHITE}{model}{RESET}",
    f"{fmt_tok(used_tok)}/{fmt_tok(total_sz)} {ctx_c}{pct_int}%{RESET}",
    f"${session_cost:.2f}",
    f"{mins}m{secs:02d}s",
    path_short,
])
sys.stdout.write(line1)

# Line 2: 5h limit | weekly limit | extra usage
if usage_data:
    parts = []

    fh = usage_data.get("five_hour") or {}
    fh_pct = round(float(fh.get("utilization") or 0))
    fh_reset = fmt_reset(fh.get("resets_at"), "time")
    fh_c = usage_color(fh_pct)
    fh_str = f"5h: {fh_c}{fh_pct}%{RESET}"
    if fh_reset:
        fh_str += f" resets {fh_reset}"
    parts.append(fh_str)

    sd = usage_data.get("seven_day") or {}
    sd_pct = round(float(sd.get("utilization") or 0))
    sd_reset = fmt_reset(sd.get("resets_at"), "datetime")
    sd_c = usage_color(sd_pct)
    sd_str = f"week: {sd_c}{sd_pct}%{RESET}"
    if sd_reset:
        sd_str += f" resets {sd_reset}"
    parts.append(sd_str)

    extra = usage_data.get("extra_usage") or {}
    if extra.get("is_enabled"):
        ex_used  = round(float(extra.get("used_credits") or 0) / 100, 2)
        ex_limit = round(float(extra.get("monthly_limit") or 0) / 100, 2)
        ex_left  = ex_limit - ex_used
        ex_pct   = round(float(extra.get("utilization") or 0))
        ex_c     = usage_color(ex_pct)
        parts.append(f"extra: {ex_c}${ex_used:.2f}{RESET}/${ex_limit:.2f} (${ex_left:.2f} left)")

    sys.stdout.write("\n" + SEP.join(parts))

# Line 3: git (only if in repo)
if git_info:
    line3_parts = [git_info]
    if lines_add or lines_rm:
        line3_parts.append(f"{GREEN}+{lines_add}{RESET}/{RED}-{lines_rm}{RESET}")
    sys.stdout.write("\n" + SEP.join(line3_parts))
