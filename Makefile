# ================================================================
# ZAMP AP AI Employee — Makefile
# Usage: make <target>
# ================================================================

.PHONY: help deploy deploy-build pause resume logs status push setup

# Default target
help:
	@echo ""
	@echo "╔══════════════════════════════════════════════════════╗"
	@echo "║          ZAMP AP — Available Commands                ║"
	@echo "╚══════════════════════════════════════════════════════╝"
	@echo ""
	@echo "  Deployment:"
	@echo "    make deploy        — git push + restart containers (~10s)"
	@echo "    make deploy-build  — git push + full image rebuild (~5min)"
	@echo ""
	@echo "  EC2 Management:"
	@echo "    make pause         — stop EC2 (save money)"
	@echo "    make resume        — start EC2 + get new IP + start app"
	@echo ""
	@echo "  Monitoring:"
	@echo "    make logs          — tail all container logs"
	@echo "    make logs-backend  — tail backend logs only"
	@echo "    make logs-frontend — tail frontend logs only"
	@echo "    make status        — show container health status"
	@echo ""
	@echo "  Git:"
	@echo "    make push          — commit all changes and push to GitHub"
	@echo ""

# ── Deployment ─────────────────────────────────────────────────

deploy:
	@./redeploy.sh

deploy-build:
	@./redeploy.sh --build

# ── EC2 Management ─────────────────────────────────────────────

pause:
	@./pause.sh

resume:
	@./resume.sh

# ── Monitoring ─────────────────────────────────────────────────

logs:
	@ssh -i ~/Downloads/ap.pem -o StrictHostKeyChecking=no \
		ubuntu@$(shell grep EC2_HOST redeploy.sh | cut -d'"' -f2) \
		"cd ~/zamp-ap && docker compose logs -f --tail=50"

logs-backend:
	@ssh -i ~/Downloads/ap.pem -o StrictHostKeyChecking=no \
		ubuntu@$(shell grep EC2_HOST redeploy.sh | cut -d'"' -f2) \
		"docker logs -f zamp-backend --tail=50"

logs-frontend:
	@ssh -i ~/Downloads/ap.pem -o StrictHostKeyChecking=no \
		ubuntu@$(shell grep EC2_HOST redeploy.sh | cut -d'"' -f2) \
		"docker logs -f zamp-frontend --tail=50"

status:
	@EC2_HOST=$$(grep EC2_HOST redeploy.sh | cut -d'"' -f2); \
	echo ""; \
	echo "🌐 App:      http://$$EC2_HOST"; \
	echo "📖 API Docs: http://$$EC2_HOST:8080/docs"; \
	echo ""; \
	ssh -i ~/Downloads/ap.pem -o StrictHostKeyChecking=no \
		ubuntu@$$EC2_HOST \
		"cd ~/zamp-ap && docker compose ps"

# ── Git ────────────────────────────────────────────────────────

push:
	@git add -A
	@git commit -m "chore: update $(shell date '+%Y-%m-%d %H:%M')" 2>/dev/null || echo "Nothing to commit"
	@git push origin main
	@echo "✅ Pushed to GitHub"
