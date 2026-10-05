#!/usr/bin/env bash
# ================================================================
# ZAMP AP — One-Command Redeploy Script
# Usage: ./redeploy.sh [--build]
#
# What it does:
#   1. Pushes local changes to GitHub
#   2. SSHes into EC2
#   3. git pull (latest code)
#   4. Optionally rebuilds Docker images (--build flag)
#   5. Restarts all containers
# ================================================================

set -e

# ── Config ──────────────────────────────────────────────────────
EC2_HOST="100.26.131.63"
EC2_USER="ubuntu"
EC2_KEY="$HOME/Downloads/ap.pem"
APP_DIR="~/zamp-ap"
GITHUB_REPO="https://github.com/sohansouri47/AP-.git"
GITHUB_BRANCH="main"
# ────────────────────────────────────────────────────────────────

REBUILD=false
if [[ "$1" == "--build" ]]; then
  REBUILD=true
fi

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║        ZAMP AP — Redeploy to AWS EC2                ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Push to GitHub ──────────────────────────────────────
echo "▶ Step 1: Pushing latest code to GitHub..."
git add -A
git commit -m "chore: redeploy $(date '+%Y-%m-%d %H:%M')" 2>/dev/null || echo "  (nothing new to commit)"
git push origin "$GITHUB_BRANCH"
echo "  ✅ GitHub up to date."
echo ""

# ── Step 2: SSH into EC2 and deploy ────────────────────────────
echo "▶ Step 2: Connecting to EC2 (${EC2_HOST})..."
echo ""

ssh -i "$EC2_KEY" -o StrictHostKeyChecking=no "${EC2_USER}@${EC2_HOST}" bash -s << REMOTE_SCRIPT
set -e

echo "  📦 Pulling latest code from GitHub..."
cd ${APP_DIR}
git pull origin ${GITHUB_BRANCH}
echo ""

if [ "$REBUILD" = true ]; then
  echo "  🔨 Rebuilding Docker images (--build flag set)..."
  docker compose build --no-cache
  echo "  ✅ Images rebuilt."
  echo ""
fi

echo "  🚀 Restarting containers..."
docker compose down
docker compose up -d
echo ""

echo "  ⏳ Waiting 15s for containers to stabilise..."
sleep 15

echo "  📊 Container status:"
docker compose ps
echo ""

echo "  ✅ Deployment complete!"
REMOTE_SCRIPT

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  🌐 App live at: http://${EC2_HOST}                  ║"
echo "║  📖 API Docs:    http://${EC2_HOST}:8080/docs        ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
