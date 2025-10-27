#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}Generating test load for WeasyPrint Service...${NC}"
echo ""

# Configuration
BASE_URL="http://localhost:9080"
REQUESTS=${1:-100}
CONCURRENCY=${2:-10}

echo -e "${YELLOW}Configuration:${NC}"
echo -e "  Requests:    ${REQUESTS}"
echo -e "  Concurrency: ${CONCURRENCY}"
echo ""

# Check if service is running
if ! curl -sf ${BASE_URL}/health > /dev/null 2>&1; then
    echo -e "${RED}Error: WeasyPrint service is not running at ${BASE_URL}${NC}"
    echo -e "${YELLOW}Run ./monitoring/start-monitoring.sh first${NC}"
    exit 1
fi

# Function to send PDF generation request
send_pdf_request() {
    local id=$1
    curl -s -X POST ${BASE_URL}/convert/html \
         -H "Content-Type: text/html" \
         -d "<html><body><h1>Test Document $id</h1><p>Generated at $(date)</p></body></html>" \
         -o /dev/null
}

# Function to send SVG conversion request
send_svg_request() {
    local id=$1
    curl -s -X POST ${BASE_URL}/convert/html \
         -H "Content-Type: text/html" \
         -d "<html><body><svg width=\"200\" height=\"200\"><circle cx=\"100\" cy=\"100\" r=\"50\" fill=\"blue\"/><text x=\"100\" y=\"110\" text-anchor=\"middle\" fill=\"white\">Test $id</text></svg></body></html>" \
         -o /dev/null
}

# Generate mixed load
echo -e "${YELLOW}Generating ${REQUESTS} requests...${NC}"
echo -n "Progress: "

count=0
pids=()

for i in $(seq 1 $REQUESTS); do
    # Mix of PDF and SVG requests
    if [ $((i % 3)) -eq 0 ]; then
        send_svg_request $i &
    else
        send_pdf_request $i &
    fi

    pids+=($!)
    count=$((count + 1))

    # Limit concurrency
    if [ ${#pids[@]} -ge $CONCURRENCY ]; then
        wait ${pids[0]}
        pids=("${pids[@]:1}")
    fi

    # Progress indicator
    if [ $((count % 10)) -eq 0 ]; then
        echo -n "."
    fi
done

# Wait for remaining requests
for pid in "${pids[@]}"; do
    wait $pid
done

echo -e " ${GREEN}Done!${NC}"
echo ""
echo -e "${GREEN}Generated ${REQUESTS} requests${NC}"
echo ""
echo -e "${BLUE}Check metrics at:${NC}"
echo -e "  • Service Dashboard: ${YELLOW}http://localhost:9080/dashboard${NC}"
echo -e "  • Prometheus:        ${YELLOW}http://localhost:9090/graph${NC}"
echo -e "  • Grafana:           ${YELLOW}http://localhost:3000/d/weasyprint-service${NC}"
echo ""
