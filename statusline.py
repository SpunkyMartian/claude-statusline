#!/usr/bin/env python3
"""
Custom Claude Code statusline — text-only, no emojis.

Line 1: model | context tokens/total %  | session $/ today $/ block $(time left) | burn rate | path
Line 2: git branch +staged ~modified ?untracked | +added/-removed

Uses native Claude Code JSON for context/cost/git data.
Calls ccusage as subprocess for daily total, 5h block status, and burn rate.
Git info cached to /tmp to avoid lag in large repos.
"""
import json, sys, subprocess, os, re, time

data = json.load(sys.stdin)
raw_json = json.dumps(data)

# ── ANSI colors (no emojis) ──
RESET  = '\033[0m'
DIM    = '\033[2m'
GREEN  = '\033[32m'
YELLOW = '\033[33m'
RED    = '\033[31m'

# ── Model ──
model = data.get('model', {}).get('display_name', '?')

# ── Context window ──
ctx       = data.get('context_window', {})
pct       = ctx.get('used_percentage') or 0
pct_int   = int(pct)
total_sz  = ctx.get('context_window_size', 200000)
cur       = ctx.get('current_usage') or {}
used_tok  = (cur.get('input_tokens') or 0) + \
            (cur.get('cache_creation_input_tokens') or 0) + \
            (cur.get('cache_read_input_tokens') or 0)

def fmt_tok(n):
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}k"
    return str(n)

ctx_color = RED if pct_int >= 90 else YELLOW if pct_int >= 70 else GREEN

# ── Cost & duration (native) ──
cost_obj     = data.get('cost', {})
session_cost = cost_obj.get('total_cost_usd') or 0
duration_ms  = cost_obj.get('total_duration_ms') or 0
lines_add    = cost_obj.get('total_lines_added') or 0
lines_rm     = cost_obj.get('total_lines_removed') or 0
mins = duration_ms // 60000
secs = (duration_ms % 60000) // 1000

# ── Path (shorten ~) ──
cwd  = data.get('workspace', {}).get('current_dir') or data.get('cwd', '')
home = os.path.expanduser('~')
path_short = ('~' + cwd[len(home):]) if cwd.startswith(home) else cwd

# ── ccusage: daily total, block status, burn rate ──
CCUSAGE_CACHE = '/tmp/claude-statusline-ccusage-cache'
CCUSAGE_MAX_AGE = 30  # seconds — ccusage is slower, cache longer

daily = block = burn = ''

def ccusage_cache_stale():
    if not os.path.exists(CCUSAGE_CACHE):
        return True
    return (time.time() - os.path.getmtime(CCUSAGE_CACHE)) > CCUSAGE_MAX_AGE

try:
    if ccusage_cache_stale():
        out = subprocess.check_output(
            ['npx', 'ccusage@latest', 'statusline'],
            input=raw_json, text=True, stderr=subprocess.DEVNULL, timeout=15
        ).strip()
        with open(CCUSAGE_CACHE, 'w') as f:
            f.write(out)
    else:
        with open(CCUSAGE_CACHE) as f:
            out = f.read().strip()

    # Parse ccusage output:
    # "🤖 Opus | 💰 $0.47 session / $0.09 today / $0.51 block (28m left) | 🔥 $0.13/hr | 🧠 15,500 (8%)"
    m_daily = re.search(r'(\$[\d.]+)\s*today', out)
    m_block = re.search(r'(\$[\d.]+)\s*block\s*\(([^)]+)\)', out)
    m_burn  = re.search(r'(\$[\d.]+/hr)', out)
    if m_daily: daily = m_daily.group(1)
    if m_block: block = f"{m_block.group(1)} block ({m_block.group(2)})"
    if m_burn:  burn = m_burn.group(1)
except Exception:
    pass

# ── Git (cached 5s) ──
GIT_CACHE     = '/tmp/claude-statusline-git-cache'
GIT_MAX_AGE   = 5

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
            branch   = parts[0]
            staged   = int(parts[1])
            modified = int(parts[2])
            untracked = int(parts[3])

    pieces = [branch]
    if staged:    pieces.append(f"{GREEN}+{staged}{RESET}")
    if modified:  pieces.append(f"{YELLOW}~{modified}{RESET}")
    if untracked: pieces.append(f"{DIM}?{untracked}{RESET}")
    git_info = ' '.join(pieces)
except Exception:
    git_info = ''

# ── Build output ──
sep = f" {DIM}|{RESET} "

# Line 1: model | context | costs | burn | path
cost_parts = [f"${session_cost:.2f}"]
if daily: cost_parts.append(f"{daily} today")
if block: cost_parts.append(block)
cost_str = ' / '.join(cost_parts)

line1_items = [
    model,
    f"{fmt_tok(used_tok)}/{fmt_tok(total_sz)} {ctx_color}{pct_int}%{RESET}",
    cost_str,
]
if burn: line1_items.append(burn)
line1_items.append(path_short)
print(sep.join(line1_items))

# Line 2: git (only if in repo)
if git_info:
    line2_parts = [git_info]
    if lines_add or lines_rm:
        line2_parts.append(f"{GREEN}+{lines_add}{RESET}/{RED}-{lines_rm}{RESET}")
    print(sep.join(line2_parts))
