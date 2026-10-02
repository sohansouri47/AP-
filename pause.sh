#!/usr/bin/env bash
# ================================================================
# ZAMP AP — Pause EC2 Instance
# Usage: ./pause.sh
# ================================================================

INSTANCE_ID="i-02d0d9442cf978057"
REGION="us-east-1"
AWS="/opt/miniconda3/bin/aws"

echo ""
echo "⏸  Stopping EC2 instance ${INSTANCE_ID}..."
$AWS ec2 stop-instances --instance-ids "$INSTANCE_ID" --region "$REGION"

echo ""
echo "✅ Instance is stopping. You will not be charged for compute."
echo "   (EBS storage ~\$1.60/month still applies)"
echo ""
echo "To resume later, run:  ./resume.sh"
