#!/data/data/com.termux/files/usr/bin/bash
# termux_ai_manager.sh — Unified Termux AI Tool
# Installed by install.sh to /data/data/com.termux/files/usr/bin/

set -euo pipefail

BASE="/storage/emulated/0"
PROJECTS="$BASE/Projects"
AI="$BASE/Download/ai_openrouter"
KEY_FILE="$AI/configs/api_key.json"
PID_FILE="$AI/cache/scanner.pid"
LOG_FILE="$AI/logs/manager.log"
SCANNER="$AI/live_model_scanner.py"

log() { echo "[$(date +%H:%M:%S)] $*" >> "$LOG_FILE" 2>/dev/null || true; echo "$*"; }

mkdir -p "$PROJECTS" "$AI/configs" "$AI/logs" "$AI/cache"

# === Dependency check ===
check_deps() {
  local missing=()
  for cmd in python3 git curl jq; do
    if ! command -v "$cmd" &>/dev/null; then missing+=("$cmd"); fi
  done
  if [ ${#missing[@]} -gt 0 ]; then
    echo "📦 Installing missing: ${missing[*]}"
    pkg install -y "${missing[@]}" 2>/dev/null || {
      echo "❌ Failed to install ${missing[*]}. Run: pkg install ${missing[*]}"
      exit 1
    }
    echo "✅ Dependencies installed"
  fi
}

# === Load API key ===
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
if [ -f "$KEY_FILE" ]; then
  KEY=$(python3 -c "import json; print(json.load(open('$KEY_FILE')).get('key',''))" 2>/dev/null) || KEY=""
  [ -n "$KEY" ] && export OPENROUTER_API_KEY="$KEY"
fi

# === Validation ===
validate() {
  local ok=0
  [ -z "$OPENROUTER_API_KEY" ] && { log "❌ No API key — set with: termux-ai key <token>"; ok=1; }
  [ ! -d "$AI" ] && { log "❌ AI backend missing: $AI — run: termux-ai install"; ok=1; }
  [ ! -d "$PROJECTS" ] && { log "❌ Projects path missing: $PROJECTS"; ok=1; }
  return $ok
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
    else
      rm -f "$PID_FILE"
      [ "$cmd" = "check" ] && return 1
    fi
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
  echo "  clone <url>       Clone GitHub repo into Projects/"
  echo "  sync [project]    Push/pull project changes"
  echo "  list              List all projects with types"
  echo "  status            Show system health + model state"
  echo "  models            Show model scores & latency"
  echo "  key <token>       Set OpenRouter API key"
  echo ""
  echo "Aliases:"
  echo "  ai-status  → termux-ai status"
  echo "  ai-models  → termux-ai models"
  echo "  ai-scan    → termux-ai scan"
  echo "  ai-sync    → termux-ai sync"
}

case "${1:-help}" in
  start)
    check_deps
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║     🤖 UNIFIED TERMUX AI TOOL              ║"
    echo "╚══════════════════════════════════════════════╝"
    echo ""
    validate && { log "❌ Validation failed"; exit 1; }

    if [ -f "$SCANNER" ]; then
      proc_manager start || {
        nohup python3 "$SCANNER" "$OPENROUTER_API_KEY" --daemon > "$AI/logs/scanner.log" 2>&1 &
        echo "$!" > "$PID_FILE"
        log "✅ Scanner started (PID $!)"
      }
    else
      log "⚠️ Scanner not found: $SCANNER — run: termux-ai install"
    fi

    echo "📁 Projects: $PROJECTS/"
    echo "📁 AI backend: $AI/"
    log "✅ All systems active"
    ;;

  stop)     proc_manager stop ;;

  install)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    SOURCE="$SCRIPT_DIR/ai_openrouter"
    if [ -d "$SOURCE" ]; then
      mkdir -p "$AI"
      cp -rn "$SOURCE"/* "$AI/" 2>/dev/null || true
      log "✅ AI backend deployed to $AI/"
    else
      log "⚠️ ai_openrouter/ not found alongside this script"
      log "   Clone repo: git clone https://github.com/Liaquatali123/termux-ai-tool.git"
    fi
    chmod +x "$AI"/*.py 2>/dev/null || true
    log "✅ Install complete"
    ;;

  scan)
    check_deps
    if [ -z "$OPENROUTER_API_KEY" ]; then log "❌ No API key"; exit 1; fi
    if [ ! -f "$SCANNER" ]; then log "❌ Scanner not found — run: termux-ai install"; exit 1; fi
    python3 "$SCANNER" "$OPENROUTER_API_KEY" --once 2>&1 | tee -a "$LOG_FILE"
    log "✅ Scan complete"
    ;;

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

  list)
    echo "📁 Projects ($PROJECTS):"
    found=0
    for d in "$PROJECTS"/*/; do
      [ ! -d "$d" ] && continue
      found=1
      NAME=$(basename "$d"); TYPE="?"
      [ -f "$d/package.json" ] && TYPE="Node.js"
      [ -f "$d/requirements.txt" ] && TYPE="Python"
      [ -f "$d/index.html" ] && TYPE="HTML/JS"
      [ -f "$d/Cargo.toml" ] && TYPE="Rust"
      if [ -d "$d/.git" ]; then
        REMOTE=$(cd "$d" && git remote get-url origin 2>/dev/null || echo "no remote")
        echo "  📂 $NAME  [$TYPE]  → $REMOTE"
      else
        echo "  📂 $NAME  [$TYPE]  (local)"
      fi
    done
    [ "$found" -eq 0 ] && echo "  (empty — clone a repo: termux-ai clone <url>)"
    ;;

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

  key)
    TOKEN="${2:-}"
    [ -z "$TOKEN" ] && { log "❌ Usage: termux-ai key <token>"; exit 1; }
    echo "{\"key\":\"$TOKEN\",\"saved\":\"$(date -Iseconds)\"}" > "$KEY_FILE"
    export OPENROUTER_API_KEY="$TOKEN"
    log "✅ API key saved"
    ;;

  help|*) show_help ;;
esac
