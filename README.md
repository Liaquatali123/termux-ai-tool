# Termux AI Tool

Unified AI development environment for Android Termux — OpenRouter free models + project management + GitHub sync.

## One-line Install

```bash
pkg update -y && pkg install git -y && git clone https://github.com/anomalyco/termux-ai-tool.git && cd termux-ai-tool && bash install.sh
```

After install, reload your shell:

```bash
source ~/.bashrc
```

## Quick Start

```bash
# 1. Set your OpenRouter API key
termux-ai key 'sk-or-v1-...'

# 2. Scan for available free models
termux-ai scan

# 3. Start the AI backend
termux-ai start

# 4. Clone a project from GitHub
termux-ai clone https://github.com/user/repo.git
```

## Commands

| Command | Description |
|---------|-------------|
| `termux-ai start` | Start AI backend + background model scanner |
| `termux-ai stop` | Stop background scanner |
| `termux-ai scan` | Run model scanner once (benchmark all free models) |
| `termux-ai key <token>` | Save OpenRouter API key |
| `termux-ai clone <url>` | Clone GitHub repo into Projects |
| `termux-ai sync [project]` | Git pull + push all projects (or one) |
| `termux-ai list` | List all projects with type detection |
| `termux-ai status` | System health + model state |
| `termux-ai models` | Show model scores, latency, categories |
| `termux-ai install` | Re-deploy AI backend files |

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
├── Download/ai_openrouter/    ← AI backend (deployed by install.sh)
│   ├── autonomous_model_manager.js   — Smart model routing
│   ├── live_model_scanner.py         — Free model discovery & benchmark
│   ├── openrouter_bridge.js          — API bridge with auto-fallback
│   ├── overload_detector.js          — Busy/overloaded response detection
│   ├── busy_model_tracker.js         — Per-model cooldown tracking
│   ├── github_project_sync.js        — GitHub clone/pull/push
│   ├── project_loader.js             — Project type detection
│   ├── auto_push_system.js           — Background git auto-commit
│   ├── configs/                      — Model configs, API keys
│   ├── logs/                         — Runtime logs
│   └── cache/                        — Scanner PID, model cache
├── Projects/                   ← All cloned projects
│   ├── my-node-app/
│   ├── my-python-bot/
│   └── ...
```

## Model Auto-Rotation

The system continuously manages OpenRouter free models:

1. **Discovery** — Fetches all `:free` models from OpenRouter API every 5 min
2. **Benchmark** — Tests each model with a real completion call
3. **Scoring** — Ranks by latency, health score, and category (coding/fast/reasoning/general)
4. **Task routing** — Coding tasks → coder models, chat → fast models, reasoning → thinking models
5. **Overload handling** — Detects "Service is too busy" / 503 / 502 and instantly switches (under 1s)
6. **Cooldown** — Rate-limited models get 30s cooldown, overloaded models are skipped
7. **Fallback** — `openrouter/free` as ultimate emergency fallback

## GitHub Sync

Each project can be synced manually or auto-pushed:

```bash
# Sync all projects
termux-ai sync

# Sync one project
termux-ai sync my-project

# Clone and auto-track
termux-ai clone https://github.com/user/repo.git
```

The sync command:
- Checks `git status --porcelain` for changes
- Auto-commits with timestamp if changes found
- Skips empty commits (no "nothing to commit" errors)
- Pulls rebase before push to avoid conflicts

## Requirements

- Android device with Termux (F-Droid version recommended)
- Storage permission granted
- OpenRouter API key (free tier: https://openrouter.ai/keys)

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `termux-ai: command not found` | Run `source ~/.bashrc` or re-run `bash install.sh` |
| `Permission denied` | Run `termux-setup-storage` first |
| All models returning 429 | Rate-limited. `openrouter/free` auto-routes — wait 30s |
| Scanner won't start | Check key: `termux-ai key 'sk-or-v1-...'` then `termux-ai start` |
| Git push fails | Set up GitHub auth: `git config --global credential.helper store` |

## License

MIT
