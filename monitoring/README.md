# WeasyPrint Service Monitoring

Comprehensive monitoring setup with Prometheus and Grafana for WeasyPrint Service.

## Quick Start

### 1. Start Monitoring Stack

```bash
./start-monitoring.sh
```

This will:
- Build the WeasyPrint service Docker image
- Start Prometheus, Grafana, and WeasyPrint service
- Wait for all services to be healthy
- Generate initial test traffic
- Display access URLs

### 2. Generate Test Load

```bash
# Generate 100 requests with 10 concurrent workers
./generate-load.sh

# Custom load: 500 requests with 20 concurrent workers
./generate-load.sh 500 20
```

### 3. View Metrics

#### Service Dashboard (Built-in)
- URL: http://localhost:9080/dashboard
- Real-time metrics with auto-refresh
- Light/dark theme support

#### Grafana Dashboard
- URL: http://localhost:3000/d/weasyprint-service
- Username: `admin`
- Password: `admin`
- Pre-configured with all metrics

#### Prometheus
- URL: http://localhost:9090
- Query metrics directly
- View targets: http://localhost:9090/targets

### 4. Stop Monitoring Stack

```bash
./stop-monitoring.sh
```

## Architecture

```
┌─────────────────┐
│  WeasyPrint     │
│  Service        │──────┐
│  :9080          │      │
└─────────────────┘      │
                         │ Scrapes /metrics
                         ▼
                  ┌─────────────┐
                  │ Prometheus  │
                  │ :9090       │
                  └─────────────┘
                         │
                         │ Data source
                         ▼
                  ┌─────────────┐
                  │  Grafana    │
                  │  :3000      │
                  └─────────────┘
```

## Available Metrics

### Conversion Metrics
- `pdf_generations_total` - Total successful PDF generations
- `pdf_generation_failures_total` - Total failed PDF conversions
- `pdf_generation_error_rate_percent` - PDF generation error rate
- `svg_conversions_total` - Total successful SVG conversions
- `svg_conversion_failures_total` - Total failed SVG conversions
- `svg_conversion_error_rate_percent` - SVG conversion error rate

### Performance Metrics
- `pdf_generation_duration_seconds` - PDF generation time histogram
- `svg_conversion_duration_seconds` - SVG conversion time histogram
- `queue_time_seconds` - Request queue wait time histogram
- `http_request_duration_seconds` - HTTP request duration histogram

### Resource Metrics
- `cpu_percent` - Current CPU usage
- `system_memory_total_bytes` - Total system memory
- `system_memory_available_bytes` - Available system memory
- `chromium_memory_bytes` - Current Chromium memory usage
- `queue_size` - Current requests in queue
- `active_pdf_generations` - Active PDF generations processes

### Health Metrics
- `uptime_seconds` - Service uptime
- `chromium_restarts_total` - Browser restart count
- `chromium_consecutive_failures` - Health check failure streak

## Grafana Dashboard Panels

1. **Conversion Rate** - Real-time PDF and SVG conversion rates
2. **Error Rate** - PDF and SVG error percentages
3. **P95 Durations** - 95th percentile response times
4. **Queue Size** - Current queue depth
5. **Active Conversions** - Concurrent operations
6. **CPU Usage** - Service CPU utilization
7. **Memory Usage** - Chromium and system memory
8. **Service Uptime** - Total service uptime
9. **Chromium Restarts** - Browser restart count

## Prometheus Queries Examples

### Conversion Rate (requests/sec)
```promql
rate(pdf_generations_total[5m])
rate(svg_conversions_total[5m])
```

### Error Rate (%)
```promql
(rate(pdf_generation_failures_total[5m]) + rate(svg_conversion_failures_total[5m]))
/
(rate(pdf_generations_total[5m]) + rate(svg_conversions_total[5m])) * 100
```

### P95 Response Time
```promql
histogram_quantile(0.95, rate(pdf_generation_duration_seconds_bucket[5m]))
histogram_quantile(0.95, rate(svg_conversion_duration_seconds_bucket[5m]))
```

### Memory Usage Trend
```promql
chromium_memory_bytes / 1024 / 1024
```

## Configuration Files

### Prometheus Configuration
- File: `prometheus.yml`
- Scrape interval: 10 seconds
- Scrape timeout: 5 seconds

### Grafana Provisioning
- Datasources: `grafana/provisioning/datasources/`
- Dashboards: `grafana/provisioning/dashboards/`
- Dashboard JSON: `grafana/dashboards/weasyprint-service.json`

### Docker Compose
- File: `docker-compose.yml`
- Services: weasyprint-service, prometheus, grafana
- Networks: monitoring (bridge)
- Volumes: prometheus-data, grafana-data

## Customization

### Change Grafana Theme
Edit dashboard theme in service:
```bash
DASHBOARD_THEME=dark ./start-monitoring.sh
```

### Adjust Prometheus Scrape Interval
Edit `prometheus.yml`:
```yaml
scrape_interval: 15s  # Change this value
```

### Modify Dashboard
1. Open Grafana: http://localhost:3000
2. Navigate to dashboard
3. Click "Dashboard settings" (gear icon)
4. Click "JSON Model"
5. Copy JSON to `grafana/dashboards/weasyprint-service.json`

## Troubleshooting

### Services not starting
```bash
# Check Docker logs
docker compose -f docker-compose.yml logs

# Check individual service
docker compose -f docker-compose.yml logs weasyprint-service
docker compose -f docker-compose.yml logs prometheus
docker compose -f docker-compose.yml logs grafana
```

### Metrics not appearing
1. Check Prometheus targets: http://localhost:9090/targets
2. Verify service is exposing metrics: http://localhost:9080/metrics
3. Check Grafana datasource configuration

### Dashboard not loading
1. Verify Grafana provisioning: `docker compose -f docker-compose.yml logs grafana`
2. Check dashboard exists: http://localhost:3000/dashboards
3. Reimport dashboard manually if needed

## Clean Up

### Stop services but keep data
```bash
./stop-monitoring.sh
# Choose 'N' when asked about removing volumes
```

### Stop services and remove all data
```bash
./stop-monitoring.sh
# Choose 'Y' when asked about removing volumes
```

### Manual cleanup
```bash
docker compose -f docker-compose.yml down -v
docker rmi weasyprint-service:dev
```

## Load Testing

Use the built-in load generator:
```bash
# Light load: 100 requests, 10 concurrent
./generate-load.sh

# Medium load: 500 requests, 20 concurrent
./generate-load.sh 500 20

# Heavy load: 2000 requests, 50 concurrent
./generate-load.sh 2000 50
```

Or use the advanced load test script:
```bash
# Run comprehensive load test
uv run python scripts/load_test.py --requests 1000 --concurrency 50 --scenario complex

# Export results
uv run python scripts/load_test.py --requests 500 --concurrency 20 --output results.json
```

## Access URLs Summary

| Service | URL | Credentials |
|---------|-----|-------------|
| WeasyPrint Service | http://localhost:9080 | - |
| Service Dashboard | http://localhost:9080/dashboard | - |
| Service Health | http://localhost:9080/health?detailed=true | - |
| API Docs | http://localhost:9080/api/docs | - |
| Raw Metrics | http://localhost:9080/metrics | - |
| Prometheus | http://localhost:9090 | - |
| Grafana | http://localhost:3000 | admin/admin |
| Grafana Dashboard | http://localhost:3000/d/weasyprint-service | admin/admin |
