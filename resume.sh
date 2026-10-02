#!/usr/bin/env bash
# ================================================================
# ZAMP AP — Resume EC2 Instance + Redeploy
# Usage: ./resume.sh
# ================================================================

INSTANCE_ID="i-02d0d9442cf978057"
REGION="us-east-1"
EC2_USER="ubuntu"
EC2_KEY="$HOME/Downloads/ap.pem"
export AWS_PAGER=""

echo ""
echo "▶  Starting EC2 instance ${INSTANCE_ID}..."
aws ec2 start-instances --instance-ids "$INSTANCE_ID" --region "$REGION"

echo "⏳  Waiting for instance to be running..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$REGION"

# Fetch new public IP (it changes after stop/start)
NEW_IP=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --query "Reservations[0].Instances[0].PublicIpAddress" \
  --output text)

echo ""
echo "✅ Instance is running!"
echo "   New Public IP: ${NEW_IP}"
echo ""

# Update redeploy.sh with the new IP automatically
sed -i '' "s/EC2_HOST=\".*\"/EC2_HOST=\"${NEW_IP}\"/" redeploy.sh
echo "   ✅ Updated redeploy.sh with new IP: ${NEW_IP}"
echo ""

# Wait for SSH to be ready
echo "⏳  Waiting for SSH to be ready (30s)..."
sleep 30

# Restart docker containers on the instance
echo "▶  Restarting containers on EC2..."
ssh -i "$EC2_KEY" -o StrictHostKeyChecking=no "${EC2_USER}@${NEW_IP}" \
  "cd ~/zamp-ap && docker compose up -d"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  🌐 App live at: http://${NEW_IP}                   ║"
echo "║  📖 API Docs:    http://${NEW_IP}:8080/docs         ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
