#!/usr/bin/env bash
# =====================================================================
# ZAMP Accounts Payable AI Employee — 1-Command AWS / Production Deployer
# =====================================================================

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=====================================================================${NC}"
echo -e "${GREEN}⚡ ZAMP Accounts Payable AI Employee — Automated Deployer${NC}"
echo -e "${BLUE}=====================================================================${NC}"

# Handle subcommands: stop, logs, clean
if [ "$1" = "stop" ]; then
    echo -e "${YELLOW}Stopping all services...${NC}"
    docker compose down
    echo -e "${GREEN}Services stopped.${NC}"
    exit 0
elif [ "$1" = "logs" ]; then
    docker compose logs -f
    exit 0
elif [ "$1" = "clean" ]; then
    echo -e "${RED}Stopping services and removing database volumes...${NC}"
    docker compose down -v
    echo -e "${GREEN}Cleanup complete.${NC}"
    exit 0
fi

# 1. Check Docker Installation
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: 'docker' is not installed or not in PATH.${NC}"
    echo "Please install Docker: sudo apt install -y docker.io docker-compose-v2"
    exit 1
fi

# Determine compose command
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    echo -e "${RED}Error: Neither 'docker compose' nor 'docker-compose' was found.${NC}"
    exit 1
fi

# 2. Check for .env file
if [ ! -f .env ]; then
    if [ -f backend/.env ]; then
        echo -e "${YELLOW}Notice: Root .env not found. Copying credentials from backend/.env...${NC}"
        cp backend/.env .env
    elif [ -f .env.example ]; then
        echo -e "${YELLOW}Notice: Creating .env from .env.example...${NC}"
        cp .env.example .env
        echo -e "${RED}⚠️ Please update .env with your real OPENAI_API_KEY before starting!${NC}"
    fi
fi

# 2.1 Check Memory & Auto-Configure Swap for t3.small / low-RAM instances
if command -v free &> /dev/null; then
    TOTAL_MEM_MB=$(free -m | awk '/^Mem:/{print $2}')
    SWAP_MEM_MB=$(free -m | awk '/^Swap:/{print $2}')
    if [ "$TOTAL_MEM_MB" -lt 2500 ] && [ "$SWAP_MEM_MB" -lt 1000 ]; then
        echo -e "${YELLOW}Notice: Detected ${TOTAL_MEM_MB}MB RAM with no swap space on this instance.${NC}"
        echo -e "${YELLOW}Setting up a 2GB swapfile to prevent Out-Of-Memory (OOM) during Docker build...${NC}"
        if sudo -n true 2>/dev/null || [ "$EUID" -eq 0 ]; then
            sudo fallocate -l 2G /swapfile 2>/dev/null || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 2>/dev/null
            sudo chmod 600 /swapfile
            sudo mkswap /swapfile 2>/dev/null
            sudo swapon /swapfile 2>/dev/null
            echo -e "${GREEN}✅ 2GB Swap activated! Total available virtual memory: ~$((TOTAL_MEM_MB + 2048))MB.${NC}"
        else
            echo -e "${YELLOW}Tip: If build fails with 'Killed', run: sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile${NC}"
        fi
    fi
fi

# 3. Detect Host IP for Output
HOST_IP=$(curl -s -m 2 https://ifconfig.me 2>/dev/null || curl -s -m 2 https://api.ipify.org 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

echo -e "${BLUE}Building container images...${NC}"
$COMPOSE_CMD build

echo -e "${BLUE}Launching containers in detached mode...${NC}"
$COMPOSE_CMD up -d

echo -e "${YELLOW}Waiting for service health checks to pass (Postgres -> FastMCP -> FastAPI -> Streamlit)...${NC}"
MAX_WAIT=60
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
    UNHEALTHY=$($COMPOSE_CMD ps --format '{{.Service}} {{.Health}}' 2>/dev/null | grep -v 'healthy' || true)
    if [ -z "$UNHEALTHY" ]; then
        break
    fi
    sleep 3
    ELAPSED=$((ELAPSED + 3))
    echo -n "."
done
echo ""

echo -e "${GREEN}=====================================================================${NC}"
echo -e "${GREEN}🎉 ZAMP AP AI Employee is LIVE & HEALTHY!${NC}"
echo -e "${GREEN}=====================================================================${NC}"
echo -e "🔗 ${GREEN}Interviewer Public Link:${NC}  http://${HOST_IP}  (Standard Port 80)"
echo -e "👉 ${BLUE}Streamlit Direct:${NC}        http://${HOST_IP}:8501"
echo -e "👉 ${BLUE}FastAPI Swagger Docs:${NC}    http://${HOST_IP}:8080/docs"
echo -e "👉 ${BLUE}FastMCP SSE Endpoint:${NC}    http://${HOST_IP}:8000/sse"
echo -e "${GREEN}=====================================================================${NC}"
echo -e "Useful management commands:"
echo -e "  View live logs:      ${YELLOW}./deploy.sh logs${NC}"
echo -e "  Stop all services:   ${YELLOW}./deploy.sh stop${NC}"
echo -e "  Full reset:          ${YELLOW}./deploy.sh clean${NC}"
echo -e "${GREEN}=====================================================================${NC}"
