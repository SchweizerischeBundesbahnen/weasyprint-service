#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}WeasyPrint Service Monitoring Setup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"
if ! command_exists docker; then
    echo -e "${RED}Error: docker is not installed${NC}"
    exit 1
fi

if ! command_exists docker-compose && ! docker compose version >/dev/null 2>&1; then
    echo -e "${RED}Error: docker-compose is not installed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Prerequisites met${NC}"
echo ""

# Build the Docker image
echo -e "${YELLOW}Building WeasyPrint service Docker image...${NC}"
docker build --build-arg APP_IMAGE_VERSION=dev --file ../Dockerfile --tag weasyprint-service:dev .. || {
    echo -e "${RED}Failed to build Docker image${NC}"
    exit 1
}
echo -e "${GREEN}✓ Docker image built${NC}"
echo ""

# Start services
echo -e "${YELLOW}Starting services with Docker Compose...${NC}"
if command_exists docker-compose; then
    docker-compose -f docker-compose.yml up -d
else
    docker compose -f docker-compose.yml up -d
fi
echo -e "${GREEN}✓ Services started${NC}"
echo ""

# Wait for services to be healthy
echo -e "${YELLOW}Waiting for services to be ready...${NC}"
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

echo -n "Prometheus: "
for i in {1..30}; do
    if curl -sf http://localhost:9090/-/ready > /dev/null 2>&1; then
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

# Generate some test traffic
echo -e "${YELLOW}Generating initial test traffic...${NC}"
for i in {1..5}; do
    curl -s -X POST http://localhost:9080/convert/html \
         -H "Content-Type: text/html" \
         -d "<html><body><h1>Test PDF $i</h1></body></html>" \
         -o /dev/null 2>&1 || true
    echo -n "."
done
echo -e " ${GREEN}Done${NC}"
echo ""

# Print access information
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Services are ready!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${BLUE}Access URLs:${NC}"
echo -e "  • WeasyPrint Service:  ${YELLOW}http://localhost:9080${NC}"
echo -e "    - Health:           ${YELLOW}http://localhost:9080/health?detailed=true${NC}"
echo -e "    - Dashboard:        ${YELLOW}http://localhost:9080/dashboard${NC}"
echo -e "    - API Docs:         ${YELLOW}http://localhost:9080/api/docs${NC}"
echo -e "    - Metrics:          ${YELLOW}http://localhost:9080/metrics${NC}"
echo ""
echo -e "  • Prometheus:          ${YELLOW}http://localhost:9090${NC}"
echo -e "    - Targets:          ${YELLOW}http://localhost:9090/targets${NC}"
echo -e "    - Graph:            ${YELLOW}http://localhost:9090/graph${NC}"
echo ""
echo -e "  • Grafana:             ${YELLOW}http://localhost:3000${NC}"
echo -e "    - Username:         ${YELLOW}admin${NC}"
echo -e "    - Password:         ${YELLOW}admin${NC}"
echo -e "    - Dashboard:        ${YELLOW}http://localhost:3000/d/weasyprint-service${NC}"
echo ""
echo -e "${BLUE}Commands:${NC}"
echo -e "  • Generate test load:  ${YELLOW}./monitoring/generate-load.sh${NC}"
echo -e "  • View logs:           ${YELLOW}docker compose -f monitoring/docker-compose.yml logs -f${NC}"
echo -e "  • Stop services:       ${YELLOW}./monitoring/stop-monitoring.sh${NC}"
echo ""
echo -e "${GREEN}Tip: Open Grafana dashboard to see real-time metrics!${NC}"
echo ""
