#!/data/data/com.termux/files/usr/bin/bash
# termux_ai_manager.sh — Unified Termux AI Tool
# Self-healing startup. Never hard-fails on recoverable issues.

set -euo pipefail

BASE="/storage/emulated/0"
PROJECTS="$BASE/Projects"
AI="$BASE/Download/ai_openrouter"
KEY_FILE="$AI/configs/api_key.json"
PID_FILE="$AI/cache/scanner.pid"
LOG_FILE="$AI/logs/manager.log"
SCANNER="$AI/live_model_scanner.py"

log() { echo "[$(date +%H:%M:%S)] $*" >> "$LOG_FILE" 2>/dev/null || true; echo "$*"; }

# === Ensure core dirs ===
ensure_dirs() {
  for d in "$PROJECTS" "$AI/configs" "$AI/logs" "$AI/cache"; do
    [ -d "$d" ] || { mkdir -p "$d" && log "📁 Created: $d"; }
  done
}
ensure_dirs

# === Load API key ===
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
if [ -f "$KEY_FILE" ]; then
  KEY=$(python3 -c "import json; print(json.load(open('$KEY_FILE')).get('key',''))" 2>/dev/null) || KEY=""
  [ -n "$KEY" ] && export OPENROUTER_API_KEY="$KEY"
fi

# === Auto-fix: migrate free_model_scanner.py → live_model_scanner.py ===
[ -f "$AI/free_model_scanner.py" ] && [ ! -f "$SCANNER" ] && {
  mv "$AI/free_model_scanner.py" "$SCANNER" && log "🔄 Migrated free_model_scanner.py → live_model_scanner.py"
}

# === Dependency check + auto-install ===
check_deps() {
  local missing=() cmds=(python3 git curl jq nodejs)
  for cmd in "${cmds[@]}"; do
    command -v "$cmd" &>/dev/null || missing+=("$cmd")
  done
  [ ${#missing[@]} -eq 0 ] && return 0
  log "📦 Installing missing: ${missing[*]}"
  pkg install -y "${missing[@]}" >> "$LOG_FILE" 2>&1 || {
    log "⚠️ Auto-install failed for: ${missing[*]}"
    log "   Run manually: pkg install ${missing[*]}"
    return 1
  }
  log "✅ Dependencies installed"
}

# === Storage permission check ===
check_storage() {
  if [ ! -d "/storage/emulated/0" ]; then
    log "⚠️ Storage not accessible"
    termux-setup-storage 2>/dev/null || true
    sleep 2
    if [ ! -d "/storage/emulated/0" ]; then
      log "⚠️ Storage still unavailable — continuing in limited mode"
      return 1
    fi
  fi
  return 0
}

# === Self-healing validation (does NOT exit) ===
auto_repair() {
  local issues=0 repaired=0

  # 1. Storage
  check_storage || { issues=$((issues+1)); }

  # 2. Dirs
  ensure_dirs

  # 3. Dependencies
  check_deps || { issues=$((issues+1)); }

  # 4. API key
  if [ -z "$OPENROUTER_API_KEY" ]; then
    log "⚠️ No API key — AI inference disabled until set"
    log "   Fix: termux-ai key 'sk-or-v1-...'"
    issues=$((issues+1))
  fi

  # 5. Scanner
  if [ ! -f "$SCANNER" ]; then
    log "⚠️ Scanner missing: live_model_scanner.py"
    # Try installing from repo sibling
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd 2>/dev/null || echo "")"
    if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/ai_openrouter/live_model_scanner.py" ]; then
      cp "$SCRIPT_DIR/ai_openrouter/live_model_scanner.py" "$AI/" 2>/dev/null && {
        log "🔧 Auto-fixed: copied live_model_scanner.py"
        repaired=$((repaired+1))
      }
    fi
    [ ! -f "$SCANNER" ] && {
      log "⚠️ Scanner not deployed — run: termux-ai install"
      issues=$((issues+1))
    }
  fi

  # 6. AI backend dir
  if [ ! -d "$AI" ]; then
    log "🔧 Creating AI backend dir..."
    mkdir -p "$AI" && repaired=$((repaired+1))
  fi

  # 7. AI backend files (missing JS? deploy from repo)
  if [ ! -f "$AI/autonomous_model_manager.js" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd 2>/dev/null || echo "")"
    if [ -n "$SCRIPT_DIR" ] && [ -d "$SCRIPT_DIR/ai_openrouter" ]; then
      cp -rn "$SCRIPT_DIR/ai_openrouter"/* "$AI/" 2>/dev/null && {
        log "🔧 Deployed AI backend from repo"
        repaired=$((repaired+1))
      }
    fi
  fi

  [ "$issues" -gt 0 ] && log "⚠️ $issues issue(s) detected, $repaired repaired"
  return $issues
}

# === Process manager ===
proc_manager() {
  local cmd="$1" pid=""
  if [ -f "$PID_FILE" ]; then
    pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      case "$cmd" in
        check) return 0 ;;
        start) log "⏩ Scanner already running (PID $pid)"; return 0 ;;
        stop)  kill "$pid" 2>/dev/null || true; rm -f "$PID_FILE"; log "🛑 Scanner stopped"; return 0 ;;
      esac
    else rm -f "$PID_FILE"; fi
  fi
  [ "$cmd" = "check" ] && return 1
  return 1
}

# === Help ===
show_help() {
  echo "Usage: termux-ai <command> [args]"
  echo ""
  echo "Commands:"
  echo "  start             Start AI backend + model scanner"
  echo "  stop              Stop background scanner"
  echo "  install           Deploy/update AI backend files"
  echo "  scan              Run model scanner once"
  echo "  doctor            Run full diagnostics"
  echo "  clone <url>       Clone GitHub repo into Projects/"
  echo "  sync [project]    Push/pull project changes"
  echo "  list              List all projects with types"
  echo "  status            Show system health + model state"
  echo "  models            Show model scores & latency"
  echo "  key <token>       Set OpenRouter API key"
  echo ""
  echo "Aliases:  ai-status  ai-models  ai-scan  ai-sync"
}

case "${1:-help}" in
  # ===== START =====
  start)
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║     🤖 UNIFIED TERMUX AI TOOL              ║"
    echo "╚══════════════════════════════════════════════╝"
    echo ""

    log "🔍 Running system validation..."
    auto_repair; local repair_exit=$?

    if [ "$repair_exit" -gt 0 ]; then
      log "🚀 Starting in recovery mode (${repair_exit} issue(s))"
    else
      log "✅ Validation passed"
    fi

    # Start scanner (non-fatal if missing)
    if [ -f "$SCANNER" ] && [ -n "$OPENROUTER_API_KEY" ]; then
      proc_manager start || {
        nohup python3 "$SCANNER" "$OPENROUTER_API_KEY" --daemon > "$AI/logs/scanner.log" 2>&1 &
        echo "$!" > "$PID_FILE"
        log "✅ Scanner started (PID $!)"
      }
    else
      [ ! -f "$SCANNER" ] && log "⏩ Scanner skipped (not deployed)"
      [ -z "$OPENROUTER_API_KEY" ] && log "⏩ Scanner skipped (no API key)"
    fi

    echo "📁 Projects: $PROJECTS/"
    echo "📁 AI backend: $AI/"
    echo ""
    log "✅ System ready"
    ;;

  # ===== STOP =====
  stop) proc_manager stop ;;

  # ===== INSTALL =====
  install)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ -d "$SCRIPT_DIR/ai_openrouter" ]; then
      mkdir -p "$AI"
      cp -rn "$SCRIPT_DIR/ai_openrouter"/* "$AI/" 2>/dev/null || true
      log "✅ AI backend deployed to $AI/"
    else
      log "⚠️ ai_openrouter/ not found — clone repo first:"
      log "   git clone https://github.com/Liaquatali123/termux-ai-tool.git"
    fi
    chmod +x "$AI"/*.py 2>/dev/null || true
    log "✅ Install complete"
    ;;

  # ===== SCAN =====
  scan)
    check_deps || true
    if [ ! -f "$SCANNER" ]; then
      auto_repair
    fi
    if [ ! -f "$SCANNER" ]; then log "❌ Scanner not found — run: termux-ai install"; exit 1; fi
    if [ -z "$OPENROUTER_API_KEY" ]; then log "❌ No API key — set: termux-ai key <token>"; exit 1; fi
    python3 "$SCANNER" "$OPENROUTER_API_KEY" --once 2>&1 | tee -a "$LOG_FILE"
    log "✅ Scan complete"
    ;;

  # ===== DOCTOR =====
  doctor)
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║           🔍 SYSTEM DIAGNOSTICS             ║"
    echo "╚══════════════════════════════════════════════╝"
    echo ""

    local exit_code=0

    # Storage
    if [ -d "/storage/emulated/0" ]; then echo "✅ storage   — /storage/emulated/0 accessible"
    else echo "❌ storage   — not accessible — run: termux-setup-storage"; exit_code=1; fi

    # Dependencies
    deps_ok=0
    for cmd in python3 git curl jq nodejs; do
      command -v "$cmd" &>/dev/null && echo "✅ ${cmd}     — $(command -v "$cmd")" || { echo "❌ ${cmd}     — not found"; deps_ok=1; exit_code=1; }
    done
    [ "$deps_ok" -eq 0 ] && echo "✅ All dependencies installed" || echo "⚠️ Some dependencies missing — run: termux-ai start (auto-fixes)"

    # API key
    if [ -n "$OPENROUTER_API_KEY" ]; then echo "✅ API key  — ${OPENROUTER_API_KEY:0:12}..."
    else echo "⚠️ API key  — not set — run: termux-ai key <token>"; fi

    # Scanner
    if [ -f "$SCANNER" ]; then echo "✅ scanner  — $SCANNER"
    elif [ -f "$AI/free_model_scanner.py" ]; then echo "⚠️ scanner  — free_model_scanner.py exists (needs migration)"
    else echo "❌ scanner  — not found — run: termux-ai install"; exit_code=1; fi

    # Configs
    [ -d "$AI/configs" ] && echo "✅ configs  — $AI/configs/" || { echo "❌ configs  — missing"; mkdir -p "$AI/configs" && echo "   (auto-created)"; }
    if [ -f "$AI/configs/models_config.json" ]; then
      python3 -c "
import json
c = json.load(open('$AI/configs/models_config.json'))
print(f'   Models: {c.get(\"working_count\",0)} working, {c.get(\"rate_limited_count\",0)} rate-limited')
print(f'   Fastest: {c.get(\"fastest_model\",\"-\")} ({c.get(\"fastest_ms\",\"-\")}ms)')
" 2>/dev/null
    else echo "   (no scan data yet — run: termux-ai scan)"; fi

    # Logs
    [ -d "$AI/logs" ] && echo "✅ logs     — $AI/logs/" || { echo "❌ logs     — missing"; mkdir -p "$AI/logs"; }
    [ -f "$LOG_FILE" ] && echo "   Size: $(wc -c < "$LOG_FILE" 2>/dev/null || echo 0) bytes, $(wc -l < "$LOG_FILE" 2>/dev/null || echo 0) lines"

    # Cache
    [ -d "$AI/cache" ] && echo "✅ cache    — $AI/cache/" || { echo "❌ cache    — missing"; mkdir -p "$AI/cache"; }
    proc_manager check && echo "   Scanner PID: $(cat "$PID_FILE" 2>/dev/null || echo '-')" || echo "   Scanner: not running"

    # Backend files
    [ -f "$AI/autonomous_model_manager.js" ] && echo "✅ backend  — core files present" || { echo "❌ backend  — missing — run: termux-ai install"; exit_code=1; }

    # Projects
    [ -d "$PROJECTS" ] && echo "✅ projects — $PROJECTS/ ($(ls -d "$PROJECTS"/*/ 2>/dev/null | wc -l) project(s))" || { echo "⚠️ projects — missing"; mkdir -p "$PROJECTS"; }

    echo ""
    [ "$exit_code" -eq 0 ] && log "✅ All systems OK" || log "⚠️ $exit_code issue(s) found — run: termux-ai start (auto-repair)"
    return $exit_code
    ;;

  # ===== CLONE =====
  clone)
    URL="${2:-}"
    if [ -z "$URL" ]; then log "❌ Usage: termux-ai clone <git-url>"; exit 1; fi
    NAME=$(basename "$URL" .git)
    log "📦 Cloning $NAME..."
    [ -d "$PROJECTS/$NAME" ] && { log "❌ Already exists: $PROJECTS/$NAME"; exit 1; }
    git clone "$URL" "$PROJECTS/$NAME" 2>&1 | tee -a "$LOG_FILE"
    log "✅ Cloned to $PROJECTS/$NAME/"
    ls -la "$PROJECTS/$NAME"
    ;;

  # ===== SYNC =====
  sync)
    PROJECT="${2:-}"
    if [ -z "$PROJECT" ]; then
      for d in "$PROJECTS"/*/; do
        [ ! -d "$d/.git" ] && continue
        name=$(basename "$d")
        changes=$(cd "$d" && git status --porcelain 2>/dev/null | wc -l)
        if [ "$changes" -gt 0 ]; then
          log "🔄 $name: $changes change(s)"
          (cd "$d" && git add -A && git commit -m "Auto-sync $(date +%Y-%m-%d)" && git push) 2>/dev/null \
            && log "  ✅ $name synced" || log "  ⏩ $name skipped"
        else
          (cd "$d" && git pull --rebase) 2>/dev/null || log "  ⚠️ $name pull failed"
        fi
      done
    else
      DIR="$PROJECTS/$PROJECT"
      [ ! -d "$DIR/.git" ] && { log "❌ Not a git repo: $DIR"; exit 1; }
      changes=$(cd "$DIR" && git status --porcelain 2>/dev/null | wc -l)
      [ "$changes" -gt 0 ] && (cd "$DIR" && git add -A && git commit -m "Auto-sync $(date +%Y-%m-%d)" && git push) 2>&1 | tee -a "$LOG_FILE"
      (cd "$DIR" && git pull --rebase) 2>/dev/null || true
      log "✅ $PROJECT synced"
    fi
    ;;

  # ===== LIST =====
  list)
    echo "📁 Projects ($PROJECTS):"
    found=0
    for d in "$PROJECTS"/*/; do
      [ ! -d "$d" ] && continue; found=1
      NAME=$(basename "$d"); TYPE="?"
      [ -f "$d/package.json" ] && TYPE="Node.js"
      [ -f "$d/requirements.txt" ] && TYPE="Python"
      [ -f "$d/index.html" ] && TYPE="HTML/JS"
      [ -f "$d/Cargo.toml" ] && TYPE="Rust"
      if [ -d "$d/.git" ]; then
        REMOTE=$(cd "$d" && git remote get-url origin 2>/dev/null || echo "no remote")
        echo "  📂 $NAME  [$TYPE]  → $REMOTE"
      else echo "  📂 $NAME  [$TYPE]  (local)"; fi
    done
    [ "$found" -eq 0 ] && echo "  (empty — clone a repo: termux-ai clone <url>)"
    ;;

  # ===== STATUS =====
  status)
    echo "╔══════════════════════════════════════════════╗"
    echo "║           SYSTEM STATUS                     ║"
    echo "╚══════════════════════════════════════════════╝"
    echo ""
    [ -n "$OPENROUTER_API_KEY" ] && echo "🔑 OpenRouter:        ✅ Connected (${OPENROUTER_API_KEY:0:12}...)" \
                                    || echo "🔑 OpenRouter:        ❌ No key — termux-ai key <token>"
    local spid=""
    [ -f "$PID_FILE" ] && spid=$(cat "$PID_FILE" 2>/dev/null || echo "")
    [ -n "$spid" ] && kill -0 "$spid" 2>/dev/null && echo "🔄 Scanner:           ✅ Running (PID $spid)" \
                    || echo "🔄 Scanner:           ⏳ Not running"
    if [ -f "$AI/configs/models_config.json" ]; then
      python3 -c "
import json
c = json.load(open('$AI/configs/models_config.json'))
w=c.get('working_count',0); r=c.get('rate_limited_count',0); d=c.get('dead_count',0)
a=c.get('working_models',['-'])[0]; fast=c.get('fastest_model','-'); fm=c.get('fastest_ms','-')
last=c.get('last_updated','never')[:19]
co=len([m for m in c.get('model_details',{}).values() if m.get('cooldown_until') and m['cooldown_until']])
print(f'🧠 Active:            {a}')
print(f'📊 Working:           {w}   ⏳ Rate-limited: {r}   ❌ Dead: {d}   🧊 Cooldown: {co}')
print(f'⚡ Fastest:           {fast} ({fm}ms)')
print(f'🕐 Last scan:         {last}')
" 2>/dev/null || echo "⏳ Model data:         Run: termux-ai scan"
    fi
    echo ""
    echo "📁 AI:     $AI/ $([ -d "$AI" ] && echo '✅' || echo '❌')"
    echo "📁 Projects: $PROJECTS/ $([ -d "$PROJECTS" ] && echo '✅' || echo '❌')"
    pc=$(ls -d "$PROJECTS"/*/ 2>/dev/null | wc -l)
    echo "📂 Projects:          $pc"
    ;;

  # ===== MODELS =====
  models)
    if [ -f "$AI/configs/models_config.json" ]; then
      python3 -c "
import json
c = json.load(open('$AI/configs/models_config.json'))
print(f'{\"Model\":<55} {\"Latency\":>8} {\"Health\":>7} {\"Category\":<12}')
print('-'*82)
for m in c.get('working_models',[]):
    d = c.get('model_details',{}).get(m,{})
    lat = d.get('avg_latency','-')
    h = d.get('health_score',0)
    cat = d.get('category','general')
    lat_str = f'{lat}ms' if isinstance(lat,int) else str(lat)
    print(f'{m:<55} {lat_str:>8} {h:>7} {cat:<12}')
" 2>/dev/null || echo "⏳ No model data"
    else echo "⏳ Run: termux-ai scan"; fi
    ;;

  # ===== KEY =====
  key)
    TOKEN="${2:-}"
    [ -z "$TOKEN" ] && { log "❌ Usage: termux-ai key <token>"; exit 1; }
    echo "{\"key\":\"$TOKEN\",\"saved\":\"$(date -Iseconds)\"}" > "$KEY_FILE"
    export OPENROUTER_API_KEY="$TOKEN"
    log "✅ API key saved"
    ;;

  help|*) show_help ;;
esac
