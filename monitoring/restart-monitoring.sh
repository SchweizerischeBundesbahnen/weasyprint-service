#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Restarting WeasyPrint Monitoring Stack...${NC}"
echo ""

# Stop services
echo -e "${YELLOW}Stopping services...${NC}"
if command -v docker-compose >/dev/null 2>&1; then
    docker-compose -f docker-compose.yml down
else
    docker compose -f docker-compose.yml down
fi
echo -e "${GREEN}✓ Services stopped${NC}"
echo ""

# Start services again
echo -e "${YELLOW}Starting services...${NC}"
if command -v docker-compose >/dev/null 2>&1; then
    docker-compose -f docker-compose.yml up -d
else
    docker compose -f docker-compose.yml up -d
fi
echo -e "${GREEN}✓ Services started${NC}"
echo ""

# Wait for services
echo -e "${YELLOW}Waiting for services to be ready...${NC}"
sleep 5

echo -n "WeasyPrint service: "
for i in {1..30}; do
    if curl -sf http://localhost:9080/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Ready${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}✗ Timeout${NC}"
        exit 1
    fi
    sleep 1
    echo -n "."
done

echo -n "Grafana: "
for i in {1..30}; do
    if curl -sf http://localhost:3000/api/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Ready${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}✗ Timeout${NC}"
        exit 1
    fi
    sleep 1
    echo -n "."
done

echo ""
echo -e "${GREEN}Monitoring stack restarted successfully!${NC}"
echo -e "${BLUE}Grafana Dashboard: ${YELLOW}http://localhost:3000/d/weasyprint-service${NC}"
echo ""
