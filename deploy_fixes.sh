#!/bin/bash
# P0 Critical Fixes Deployment Script
# Run this on your server to deploy the fixes

set -e  # Exit on error

echo "=========================================="
echo "🚀 P0 Critical Fixes Deployment"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if we're in the right directory
if [ ! -f "chartink_webhook.py" ]; then
    echo -e "${RED}Error: chartink_webhook.py not found${NC}"
    echo "Please run this script from the trading-bot directory"
    exit 1
fi

echo -e "${YELLOW}Step 1: Backing up current files...${NC}"
BACKUP_DIR="backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp chartink_webhook.py kite.py "$BACKUP_DIR/"
echo -e "${GREEN}✓ Backup created in $BACKUP_DIR/${NC}"
echo ""

echo -e "${YELLOW}Step 2: Checking syntax...${NC}"
python3 -m py_compile chartink_webhook.py kite.py
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Syntax check passed${NC}"
else
    echo -e "${RED}✗ Syntax check failed!${NC}"
    exit 1
fi
echo ""

echo -e "${YELLOW}Step 3: Stopping current container...${NC}"
if command -v docker-compose &> /dev/null; then
    docker-compose down || true
elif command -v docker &> /dev/null; then
    docker stop trading-bot 2>/dev/null || true
    docker rm trading-bot 2>/dev/null || true
else
    echo -e "${YELLOW}Warning: Docker not found, skipping container stop${NC}"
fi
echo -e "${GREEN}✓ Container stopped${NC}"
echo ""

echo -e "${YELLOW}Step 4: Rebuilding and starting...${NC}"
if command -v docker-compose &> /dev/null; then
    docker-compose build --no-cache
    docker-compose up -d
elif command -v docker &> /dev/null; then
    docker build -t trading-bot .
    docker run -d \
        --name trading-bot \
        -p 8000:8000 \
        -v $(pwd)/config.json:/app/config.json \
        -v $(pwd)/trades_log.json:/app/trades_log.json \
        -v $(pwd)/positions.json:/app/positions.json \
        trading-bot
else
    echo -e "${RED}Error: Docker not found!${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Container started${NC}"
echo ""

echo -e "${YELLOW}Step 5: Waiting for startup (15 seconds)...${NC}"
sleep 15

echo -e "${YELLOW}Step 6: Health check...${NC}"
HEALTH=$(curl -s http://localhost:8000/ || echo "FAILED")
if [ "$HEALTH" != "FAILED" ]; then
    echo -e "${GREEN}✓ Health check passed${NC}"
    echo "Response: $HEALTH"
else
    echo -e "${RED}✗ Health check failed!${NC}"
    echo "Check logs: docker-compose logs -f"
    exit 1
fi
echo ""

echo -e "${YELLOW}Step 7: Cleaning up orphan GTTs...${NC}"
CLEANUP_RESULT=$(curl -s -X POST http://localhost:8000/api/gtt/cleanup || echo "FAILED")
if [ "$CLEANUP_RESULT" != "FAILED" ]; then
    echo -e "${GREEN}✓ GTT cleanup completed${NC}"
    echo "Response: $CLEANUP_RESULT"
else
    echo -e "${YELLOW}⚠ GTT cleanup API not available yet (may need more time)${NC}"
fi
echo ""

echo "=========================================="
echo -e "${GREEN}🎉 DEPLOYMENT SUCCESSFUL!${NC}"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Test dashboard: http://your-server:8000/dashboard"
echo "2. Verify GTT orders: curl http://localhost:8000/api/gtt-orders"
echo "3. Monitor logs: docker-compose logs -f"
echo ""
echo "If issues occur, rollback with:"
echo "  cp $BACKUP_DIR/* . && docker-compose restart"
echo ""
