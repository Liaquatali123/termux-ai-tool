#!/data/data/com.termux/files/usr/bin/bash
# install.sh — Termux one-line installer for termux-ai-tool
# Usage: bash install.sh

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()  { echo -e "${GREEN}✅${NC} $1"; }
info(){ echo -e "${CYAN}ℹ️${NC}  $1"; }
err() { echo -e "${RED}❌${NC} $1"; }

REPO_NAME="termux-ai-tool"
INSTALL_DIR="$HOME/.$REPO_NAME"
BIN_DIR="/data/data/com.termux/files/usr/bin"
AI_TARGET="/storage/emulated/0/Download/ai_openrouter"
PROJECTS="/storage/emulated/0/Projects"

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   🤖 TERMUX AI TOOL INSTALLER              ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo ""

# === Step 1: Storage permission ===
info "Requesting storage access..."
termux-setup-storage 2>/dev/null || true
sleep 1

# === Step 2: Install dependencies ===
info "Installing dependencies..."
pkg update -y -q 2>/dev/null || true
DEPS=(python nodejs git jq curl openssh)
for dep in "${DEPS[@]}"; do
  if ! command -v "$dep" &>/dev/null; then
    info "  Installing $dep..."
    pkg install -y "$dep" 2>/dev/null || err "Failed: $dep"
  else
    ok "$dep already installed"
  fi
done

# === Step 3: Create storage folders ===
info "Creating storage folders..."
mkdir -p "$AI_TARGET"/{configs,logs,cache}
mkdir -p "$PROJECTS"
ok "Storage: $AI_TARGET/"
ok "Projects: $PROJECTS/"

# === Step 4: Deploy AI backend ===
info "Deploying AI backend..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE="$SCRIPT_DIR/ai_openrouter"
if [ -d "$SOURCE" ]; then
  cp -rn "$SOURCE"/* "$AI_TARGET/" 2>/dev/null || true
  chmod +x "$AI_TARGET"/*.py 2>/dev/null || true
  ok "AI backend files deployed"
else
  err "ai_openrouter/ not found alongside install.sh"
fi

# === Step 5: Install termux-ai command ===
info "Installing 'termux-ai' command..."
cp "$SCRIPT_DIR/termux_ai_manager.sh" "$BIN_DIR/termux-ai"
chmod +x "$BIN_DIR/termux-ai"
ok "termux-ai → $BIN_DIR/termux-ai"

# === Step 6: Create aliases ===
info "Adding aliases to ~/.bashrc..."
ALIASES=(
  "alias ai-status='termux-ai status'"
  "alias ai-models='termux-ai models'"
  "alias ai-scan='termux-ai scan'"
  "alias ai-sync='termux-ai sync'"
)
for a in "${ALIASES[@]}"; do
  if ! grep -q "$a" "$HOME/.bashrc" 2>/dev/null; then
    echo "$a" >> "$HOME/.bashrc"
  fi
done
ok "Aliases added: ai-status, ai-models, ai-scan, ai-sync"

# === Step 7: Save repo reference ===
echo "$SCRIPT_DIR" > "$INSTALL_DIR" 2>/dev/null || true

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   ✅ INSTALLATION COMPLETE                  ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo "  1. Set your API key:"
echo "     termux-ai key 'sk-or-v1-...'"
echo ""
echo "  2. Scan for models:"
echo "     termux-ai scan"
echo ""
echo "  3. Start the AI backend:"
echo "     termux-ai start"
echo ""
echo "  4. Clone a project:"
echo "     termux-ai clone https://github.com/user/repo.git"
echo ""
echo -e "  ${CYAN}Aliases:${NC} ai-status  ai-models  ai-scan  ai-sync"
echo ""
echo -e "  ${GREEN}Reload your shell or run:${NC} source ~/.bashrc"
echo ""
