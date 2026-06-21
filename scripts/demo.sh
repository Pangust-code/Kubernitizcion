#!/usr/bin/env bash
# ─── Script de demo para la charla ────────────────────────────────────────────
#
# Ejecuta este script durante la presentación para hacer la demo paso a paso.
# Cada función corresponde a un concepto de la charla.
#
# Uso:
#   chmod +x scripts/demo.sh
#   ./scripts/demo.sh
#
# O ejecutar funciones individuales:
#   source scripts/demo.sh && demo_health_checks

set -euo pipefail

BASE_URL="http://localhost"
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

banner() {
    echo ""
    echo -e "${BLUE}══════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}══════════════════════════════════════════${NC}"
    echo ""
}

step() { echo -e "${GREEN}▶  $1${NC}"; }
info() { echo -e "${YELLOW}ℹ  $1${NC}"; }


# ─── 1. Verificar que todo está corriendo ────────────────────────────────────
demo_status() {
    banner "Estado del stack"
    docker compose ps
    echo ""
    info "Puertos expuestos:"
    info "  API (via Nginx): http://localhost"
    info "  Prometheus:      http://localhost:9090"
    info "  Grafana:         http://localhost:3000  (admin / admin123)"
}


# ─── 2. Health Checks ────────────────────────────────────────────────────────
demo_health_checks() {
    banner "Health Checks: /health y /ready"

    step "Liveness probe (¿el proceso está vivo?):"
    curl -s "${BASE_URL}/health" | python3 -m json.tool
    echo ""

    step "Readiness probe (¿puede recibir tráfico? Verifica Redis):"
    curl -s "${BASE_URL}/ready" | python3 -m json.tool
    echo ""

    step "Info de la instancia que responde:"
    curl -s "${BASE_URL}/info" | python3 -m json.tool
    echo ""

    info "Observa el campo 'hostname' — muestra qué contenedor respondió."
    info "Ejecuta varias veces para ver cómo Nginx alterna entre api1 y api2."
}


# ─── 3. Ver el balanceo de carga en acción ───────────────────────────────────
demo_load_balancing() {
    banner "Balanceo de carga: Round-Robin"

    step "10 requests seguidas — observa qué hostname responde cada vez:"
    for i in $(seq 1 10); do
        hostname=$(curl -s "${BASE_URL}/info" | python3 -c "import sys,json; print(json.load(sys.stdin)['hostname'])")
        echo "  Request $i → ${hostname}"
    done
    echo ""
    info "Nginx distribuye las requests entre api1 y api2 en orden cíclico."
}


# ─── 4. CRUD con caché ────────────────────────────────────────────────────────
demo_cache() {
    banner "Caché Redis: Cache-Aside Pattern"

    step "Primera vez — cache MISS (va a la 'base de datos'):"
    time curl -s "${BASE_URL}/items/1" | python3 -m json.tool
    echo ""

    step "Segunda vez — cache HIT (respuesta desde Redis, ~1ms):"
    time curl -s "${BASE_URL}/items/1" | python3 -m json.tool
    echo ""

    step "Listar todos los items:"
    curl -s "${BASE_URL}/items/" | python3 -m json.tool
    echo ""

    step "Crear un item nuevo (invalida el caché de la lista):"
    curl -s -X POST "${BASE_URL}/items/" \
        -H "Content-Type: application/json" \
        -d '{"name": "Monitor 4K", "description": "32 pulgadas", "price": 399.99}' | python3 -m json.tool
    echo ""

    info "Abre Redis Commander o usa: docker exec demo-redis redis-cli KEYS '*'"
}


# ─── 5. Rate Limiting ─────────────────────────────────────────────────────────
demo_rate_limiting() {
    banner "Rate Limiting"

    step "Enviar 35 requests rápidas (límite: 30/minuto):"
    local success=0 limited=0
    for i in $(seq 1 35); do
        status=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/items/1")
        if [ "$status" = "200" ]; then
            ((success++))
        elif [ "$status" = "429" ]; then
            ((limited++))
        fi
    done
    echo "  Exitosas: ${success}"
    echo "  Rate limited (429): ${limited}"
    echo ""
    info "Las primeras 30 pasan. Las siguientes reciben HTTP 429 Too Many Requests."
    info "Grafana mostrará un spike en la métrica 'rate_limit_hits_total'."
}


# ─── 6. Métricas en Prometheus ────────────────────────────────────────────────
demo_metrics() {
    banner "Métricas de Prometheus"

    step "Métricas raw de la app (formato texto que Prometheus scrapea):"
    curl -s "${BASE_URL}/metrics" | grep -E "^(http_requests|cache_hits|cache_misses|http_active)" | head -30
    echo ""

    step "Generar tráfico para ver en Grafana:"
    info "Enviando 50 requests..."
    for i in $(seq 1 50); do
        curl -s "${BASE_URL}/items/$(( RANDOM % 3 + 1 ))" > /dev/null &
    done
    wait
    echo "  Listo. Abre Grafana: http://localhost:3000"
}


# ─── 7. Rolling Update sin downtime (Versión Kubernetes) ─────────────────────
demo_rolling_update() {
    banner "Rolling Update nativo: Actualizar sin downtime"

    info "ANTES del update — los pods están en la versión actual:"
    for i in $(seq 1 4); do
        curl -s "${BASE_URL}/info" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"  Pod {d.get('hostname','?')} → v{d.get('version','?')}\")" 2>/dev/null || true
    done
    echo ""

    step "Construyendo la nueva imagen v2.0.0 dentro de Minikube..."
    # Se asume que ejecutaste 'eval $(minikube docker-env)' en la terminal antes de iniciar el script
    docker build -t demo-api:2.0.0 --build-arg APP_VERSION=2.0.0 . > /dev/null

    step "Lanzando el Rolling Update con un solo comando (kubectl set image)..."
    kubectl set image deployment/api-deployment api=demo-api:2.0.0

    step "Observando el tráfico durante la transición:"
    # Hacemos peticiones continuamente. K8s se encarga de no enrutar tráfico
    # a los pods nuevos hasta que su /ready devuelva OK.
    for i in $(seq 1 20); do
        info_json=$(curl -s -m 2 "${BASE_URL}/info" 2>/dev/null || echo '{"hostname":"?","version":"?"}')
        hostname=$(echo "$info_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('hostname', '?'))" 2>/dev/null || echo "?")
        version=$(echo "$info_json"  | python3 -c "import sys,json; print(json.load(sys.stdin).get('version', '?'))"  2>/dev/null || echo "?")
        
        echo "  Request $i → Pod: ${hostname} (v${version})"
        sleep 1
    done
    echo ""

    info "El Deployment apagó los pods viejos y levantó los nuevos gradualmente."
    info "¡Cero downtime gestionado 100% por Kubernetes!"
}


# ─── 8. Simular fallo y recuperación (Versión Kubernetes) ────────────────────
demo_failure() {
    banner "Resiliencia: Auto-sanación (Self-healing) en K8s"

    info "Estado de los pods ANTES del fallo:"
    kubectl get pods -l app=demo-api
    echo ""

    # Obtenemos dinámicamente el nombre exacto del primer pod
    POD_NAME=$(kubectl get pods -l app=demo-api -o jsonpath='{.items[0].metadata.name}')

    step "Simulando un crash catastrófico: Eliminando el pod $POD_NAME..."
    # Lo eliminamos en segundo plano (&) para poder seguir haciendo peticiones inmediatamente
    kubectl delete pod "$POD_NAME" &
    
    sleep 1

    step "Tráfico durante la caída:"
    for i in $(seq 1 6); do
        hostname=$(curl -s -m 2 "${BASE_URL}/info" | python3 -c "import sys,json; print(json.load(sys.stdin).get('hostname', '?'))" 2>/dev/null || echo "?")
        echo "  Request $i → Respondido por: ${hostname}"
        sleep 0.5
    done
    echo ""

    info "El Service de K8s detectó la caída y envió todo el tráfico al pod sobreviviente."
    
    step "Kubernetes se dio cuenta de que faltaba una réplica. Veamos qué hizo:"
    kubectl get pods -l app=demo-api
    echo ""
    info "¡Levantó un pod de reemplazo automáticamente para mantener el estado deseado (replicas: 2)!"
}

# ─── Menú principal ───────────────────────────────────────────────────────────
main() {
    banner "Demo: Mas alla del Localhost"
    echo "  1) Estado del stack"
    echo "  2) Health checks"
    echo "  3) Balanceo de carga"
    echo "  4) Caché con Redis"
    echo "  5) Rate limiting"
    echo "  6) Métricas (Prometheus)"
    echo "  7) Rolling update"
    echo "  8) Fallo y recuperación"
    echo ""
    read -rp "Elige una opción (1-8): " choice

    case $choice in
        1) demo_status ;;
        2) demo_health_checks ;;
        3) demo_load_balancing ;;
        4) demo_cache ;;
        5) demo_rate_limiting ;;
        6) demo_metrics ;;
        7) demo_rolling_update ;;
        8) demo_failure ;;
        *) echo "Opción inválida" ;;
    esac
}

main "$@"
