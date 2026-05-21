# Termux AI Tool

Unified AI development environment for Android Termux — Python-based, self-healing, OpenRouter free models + GitHub project sync.

## Installation

```bash
pkg update -y
pkg install git -y
git clone https://github.com/Liaquatali123/termux-ai-tool.git
cd termux-ai-tool
python3 install.py
```

After install, reload your shell:
```bash
source ~/.bashrc
```

Grant storage permission if prompted:
```bash
termux-setup-storage
```

## Quick Start

```bash
# 1. Set your OpenRouter API key
termux-ai key 'sk-or-v1-...'

# 2. Run diagnostics (auto-repair any issues)
termux-ai doctor

# 3. Scan for available free models
termux-ai scan

# 4. Start the AI backend
termux-ai start
```

## Commands

| Command | Description |
|---------|-------------|
| `termux-ai start` | Validate, auto-repair, launch scanner + backend |
| `termux-ai stop` | Stop background scanner daemon |
| `termux-ai restart` | Graceful scanner restart |
| `termux-ai doctor` | Full 10-point system diagnostics |
| `termux-ai status` | System health + model state |
| `termux-ai scan` | Benchmark all free models once |
| `termux-ai models` | Show model scores, latency, categories |
| `termux-ai key <token>` | Save OpenRouter API key |
| `termux-ai clone <url>` | Clone GitHub repo into Projects |
| `termux-ai sync` | Git pull + push all projects |
| `termux-ai list` | List all projects with type detection |

### Aliases

| Alias | Maps to |
|-------|---------|
| `ai-status` | `termux-ai status` |
| `ai-models` | `termux-ai models` |
| `ai-scan` | `termux-ai scan` |
| `ai-sync` | `termux-ai sync` |

## Architecture

```
/storage/emulated/0/
├── Download/ai_openrouter/       ← Python AI backend manager
│   ├── termux_ai_manager.py      ← CLI entry point
│   ├── auto_repair.py            ← Self-healing system
│   ├── daemon_manager.py         ← PID / watchdog / background mgmt
│   ├── dependency_manager.py     ← Auto-install deps
│   ├── runtime_validator.py      ← Diagnostics (doctor)
│   ├── storage_manager.py        ← Path / dir management
│   ├── github_sync.py            ← Clone / pull / push
│   ├── project_manager.py        ← Project listing + type detection
│   ├── live_model_scanner.py     ← Free model discovery & benchmark
│   ├── autonomous_model_manager.js  — Smart model routing
│   ├── overload_detector.js         — Busy/overloaded response detection
│   ├── busy_model_tracker.js        — Per-model cooldown tracking
│   ├── configs/                     — Model configs, API keys
│   ├── logs/                        — Runtime logs (manager.log, scanner.log)
│   └── cache/                       — Scanner PID, model cache
└── Projects/                    ← All cloned projects
    ├── my-node-app/
    ├── my-python-bot/
    └── ...
```

## Self-Healing System

The Python runtime automatically repairs common issues on every `start`:

| Issue | Auto-Fix |
|-------|----------|
| Missing directories | Created automatically |
| Missing dependencies (`python3`, `git`, `curl`, `jq`, `nodejs`) | Installed via `pkg` |
| Missing scanner (`live_model_scanner.py`) | Migrated from `free_model_scanner.py` or deployed from repo |
| Corrupted/stub config | Regenerated with defaults |
| Stale PID file | Cleaned automatically |
| Storage permission missing | Detected, warned — continues in limited mode |

If any issue is unrecoverable, the system starts in **recovery mode** — still functional, with background repair.

## Model Auto-Rotation

The system continuously manages OpenRouter free models via the Python daemon:

1. **Discovery** — Fetches all `:free` models from OpenRouter API every 5 min
2. **Benchmark** — Tests each model with a real completion call
3. **Scoring** — Ranks by latency, health score, and category (coding/fast/reasoning/general)
4. **Task routing** — Coding tasks → coder models, chat → fast models, reasoning → thinking models
5. **Overload handling** — Detects "Service is too busy" / 503 / 502 and instantly switches (under 1s)
6. **Cooldown** — Rate-limited models get 30s cooldown, overloaded models are skipped
7. **Fallback** — `openrouter/free` as ultimate emergency fallback

## GitHub Sync

```bash
# Sync all projects (auto-commit changes + pull)
termux-ai sync

# Clone a project
termux-ai clone https://github.com/user/repo.git

# List all projects with types
termux-ai list
```

The sync command:
- Checks `git status --porcelain` before committing
- Auto-commits with timestamp if changes found
- Skips empty commits (no "nothing to commit" errors)
- Pulls rebase before push to avoid conflicts

## Requirements

- Android device with Termux (F-Droid version recommended)
- Storage permission granted (`termux-setup-storage`)
- OpenRouter API key (free tier: https://openrouter.ai/keys)

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `termux-ai: command not found` | Run `source ~/.bashrc` or reinstall |
| `Permission denied` | Run `termux-setup-storage` |
| All models returning 429 | Rate-limited. `openrouter/free` auto-routes — wait 30s |
| Scanner won't start | Run `termux-ai doctor` for diagnostics |
| `doctor` shows missing files | Run `termux-ai start` (auto-repair) |
| Git push fails | `git config --global credential.helper store` |

## License

MIT
