#!/bin/bash
set -e

# Get absolute path to script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_COMPOSE_PATH="${SCRIPT_DIR}/docker-compose.yml"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Stopping WeasyPrint Monitoring Stack${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Stop services
echo -e "${YELLOW}Stopping services...${NC}"
if command_exists docker-compose; then
    docker-compose -f "${DOCKER_COMPOSE_PATH}" down
else
    docker compose -f "${DOCKER_COMPOSE_PATH}" down
fi
echo -e "${GREEN}✓ Services stopped${NC}"
echo ""

# Optional: Remove volumes
read -p "Do you want to remove persistent data (Prometheus/Grafana)? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Removing volumes...${NC}"
    if command_exists docker-compose; then
        docker-compose -f "${DOCKER_COMPOSE_PATH}" down -v
    else
        docker compose -f "${DOCKER_COMPOSE_PATH}" down -v
    fi
    echo -e "${GREEN}✓ Volumes removed${NC}"
fi

echo ""
echo -e "${GREEN}Monitoring stack stopped successfully${NC}"
echo ""
