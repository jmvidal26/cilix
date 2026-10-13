#!/bin/bash

# Monitor de RAM para Cilix v1.2
# Monitorea uso de RAM y optimiza automáticamente

set -e

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuración
ALERT_THRESHOLD=${1:-5800}  # MB, por defecto 5.8GB
LOG_FILE=${2:-"/tmp/cilix-ram.log"}
CHECK_INTERVAL=5  # segundos
MAX_SAMPLES=100

print_header() {
    echo -e "${BLUE}"
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║                    Monitor de RAM Cilix                  ║"
    echo "║               Optimización para sistemas 8GB             ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_status() {
    echo -e "${GREEN}[+]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_alert() {
    echo -e "${RED}[ALERTA]${NC} $1"
}

get_ram_usage() {
    # Obtener uso de RAM en MB
    if command -v free &> /dev/null; then
        # Usar free
        TOTAL_MB=$(free -m | awk '/^Mem:/{print $2}')
        USED_MB=$(free -m | awk '/^Mem:/{print $3}')
        AVAILABLE_MB=$(free -m | awk '/^Mem:/{print $7}')
        PERCENTAGE=$((USED_MB * 100 / TOTAL_MB))
    elif [ -f /proc/meminfo ]; then
        # Usar /proc/meminfo
        TOTAL_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
        AVAILABLE_KB=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
        TOTAL_MB=$((TOTAL_KB / 1024))
        AVAILABLE_MB=$((AVAILABLE_KB / 1024))
        USED_MB=$((TOTAL_MB - AVAILABLE_MB))
        PERCENTAGE=$((USED_MB * 100 / TOTAL_MB))
    else
        echo "Error: No se puede obtener información de RAM"
        exit 1
    fi
    
    echo "$TOTAL_MB $USED_MB $AVAILABLE_MB $PERCENTAGE"
}

get_process_ram() {
    # Obtener RAM usada por procesos clave de Cilix
    PYTHON_RAM=0
    NODE_RAM=0
    OLLAMA_RAM=0
    
    # Python (servidor Cilix)
    if pgrep -f "python.*main.py" > /dev/null; then
        PYTHON_RAM=$(ps -o rss= $(pgrep -f "python.*main.py") | awk '{sum+=$1} END {print int(sum/1024)}')
    fi
    
    # Node.js (Electron)
    if pgrep -f "electron" > /dev/null; then
        NODE_RAM=$(ps -o rss= $(pgrep -f "electron") | awk '{sum+=$1} END {print int(sum/1024)}')
    fi
    
    # Ollama
    if pgrep -f "ollama" > /dev/null; then
        OLLAMA_RAM=$(ps -o rss= $(pgrep -f "ollama") | awk '{sum+=$1} END {print int(sum/1024)}')
    fi
    
    echo "$PYTHON_RAM $NODE_RAM $OLLAMA_RAM"
}

log_message() {
    local message="$1"
    local level="${2:-INFO}"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    echo "[$timestamp] [$level] $message" >> "$LOG_FILE"
    
    if [ "$level" = "ALERT" ]; then
        print_alert "$message"
    elif [ "$level" = "WARNING" ]; then
        print_warning "$message"
    else
        print_status "$message"
    fi
}

optimize_memory() {
    local used_mb="$1"
    local total_mb="$2"
    local threshold="$3"
    
    if [ "$used_mb" -gt "$threshold" ]; then
        log_message "RAM alta: ${used_mb}MB/${total_mb}MB (>${threshold}MB)" "ALERT"
        
        # Estrategias de optimización
        
        # 1. Descargar modelo Re si está cargado
        if [ -f "/tmp/cilix-re-loaded" ]; then
            log_message "Intentando descargar modelo Re para liberar RAM..." "WARNING"
            curl -X POST http://localhost:8765/api/unload-re 2>/dev/null || true
            rm -f /tmp/cilix-re-loaded
            log_message "Modelo Re descargado" "INFO"
        fi
        
        # 2. Limpiar cache de Python
        log_message "Limpiando cache de Python..." "INFO"
        python3 -c "import sys; sys.path.append('.'); from backend.core_ia import CoreIA; import asyncio; asyncio.run(CoreIA().cleanup())" 2>/dev/null || true
        
        # 3. Limpiar cache del sistema (si hay permisos)
        if [ "$(id -u)" -eq 0 ]; then
            log_message "Limpiando page cache..." "INFO"
            sync
            echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
        fi
        
        # 4. Reducir calidad texturas VTuber (si aplica)
        if [ -f "/tmp/cilix-vtuber-running" ]; then
            log_message "Reduciendo calidad texturas VTuber..." "WARNING"
            curl -X POST http://localhost:8765/api/reduce-texture-quality 2>/dev/null || true
        fi
        
        log_message "Optimizaciones aplicadas" "INFO"
        return 0
    fi
    
    return 1
}

show_dashboard() {
    clear
    print_header
    
    # Obtener métricas
    read total used available percentage <<< $(get_ram_usage)
    read python_ram node_ram ollama_ram <<< $(get_process_ram)
    
    # Calcular otros procesos
    other_ram=$((used - python_ram - node_ram - ollama_ram))
    
    # Mostrar dashboard
    echo -e "${CYAN}📊 Dashboard de RAM - $(date '+%H:%M:%S')${NC}"
    echo "══════════════════════════════════════════════"
    echo ""
    echo -e "${BLUE}📈 Uso Total:${NC}"
    echo -e "   Total:     ${YELLOW}${total}MB${NC}"
    echo -e "   Usado:     ${RED}${used}MB${NC} (${percentage}%)"
    echo -e "   Disponible: ${GREEN}${available}MB${NC}"
    echo ""
    echo -e "${BLUE}🔧 Procesos Cilix:${NC}"
    echo -e "   Python:    ${YELLOW}${python_ram}MB${NC}"
    echo -e "   Electron:  ${YELLOW}${node_ram}MB${NC}"
    echo -e "   Ollama:    ${YELLOW}${ollama_ram}MB${NC}"
    echo -e "   Otros:     ${YELLOW}${other_ram}MB${NC}"
    echo ""
    echo -e "${BLUE}⚠️  Umbral de Alerta:${NC} ${ALERT_THRESHOLD}MB"
    echo ""
    
    # Barra de progreso
    echo -e "${BLUE}📊 Gráfico:${NC}"
    local bar_width=50
    local filled=$((percentage * bar_width / 100))
    local empty=$((bar_width - filled))
    
    echo -n "["
    for ((i=0; i<filled; i++)); do echo -n "█"; done
    for ((i=0; i<empty; i++)); do echo -n "░"; done
    echo -e "] ${percentage}%"
    echo ""
    
    # Estado
    if [ "$used" -gt "$ALERT_THRESHOLD" ]; then
        echo -e "${RED}🚨 ALERTA: RAM CRÍTICA${NC}"
    elif [ "$percentage" -gt 85 ]; then
        echo -e "${YELLOW}⚠️  ADVERTENCIA: RAM ALTA${NC}"
    else
        echo -e "${GREEN}✅ RAM NORMAL${NC}"
    fi
    
    echo ""
    echo "══════════════════════════════════════════════"
    echo -e "${CYAN}📝 Log:${NC} $LOG_FILE"
    echo -e "${CYAN}⏱️  Intervalo:${NC} ${CHECK_INTERVAL}s"
    echo "══════════════════════════════════════════════"
}

monitor_loop() {
    local samples=0
    
    log_message "Iniciando monitor de RAM Cilix v1.2" "INFO"
    log_message "Umbral de alerta: ${ALERT_THRESHOLD}MB" "INFO"
    
    while true; do
        # Obtener métricas
        read total used available percentage <<< $(get_ram_usage)
        
        # Mostrar dashboard
        show_dashboard
        
        # Registrar métricas
        log_message "RAM: ${used}MB/${total}MB (${percentage}%) - Python: ${python_ram}MB, Node: ${node_ram}MB, Ollama: ${ollama_ram}MB" "MONITOR"
        
        # Optimizar si es necesario
        optimize_memory "$used" "$total" "$ALERT_THRESHOLD"
        
        # Controlar tasa de muestreo
        samples=$((samples + 1))
        if [ "$samples" -ge "$MAX_SAMPLES" ]; then
            log_message "Rotando archivo de log..." "INFO"
            # Rotar log si es muy grande
            if [ -f "$LOG_FILE" ] && [ "$(stat -c%s "$LOG_FILE")" -gt 10485760 ]; then
                mv "$LOG_FILE" "${LOG_FILE}.1"
                log_message "Log rotado" "INFO"
            fi
            samples=0
        fi
        
        # Esperar antes de la siguiente verificación
        sleep "$CHECK_INTERVAL"
    done
}

show_help() {
    echo "Monitor de RAM para Cilix v1.2"
    echo ""
    echo "Uso: $0 [OPCIONES]"
    echo ""
    echo "Opciones:"
    echo "  <umbral>          Umbral de alerta en MB (default: 5800)"
    echo "  --log <archivo>   Archivo de log (default: /tmp/cilix-ram.log)"
    echo "  --interval <seg>  Intervalo de verificación (default: 5)"
    echo "  --dashboard       Solo mostrar dashboard una vez"
    echo "  --status          Estado actual de RAM"
    echo "  --optimize        Forzar optimización ahora"
    echo "  --help            Mostrar esta ayuda"
    echo ""
    echo "Ejemplos:"
    echo "  $0 6000                    # Alerta a 6GB"
    echo "  $0 --log /var/log/cilix-ram.log"
    echo "  $0 --dashboard             # Dashboard interactivo"
    echo "  $0 --status                # Estado rápido"
}

main() {
    # Manejar argumentos
    case "${1:-}" in
        "--help")
            show_help
            exit 0
            ;;
        "--dashboard")
            show_dashboard
            exit 0
            ;;
        "--status")
            read total used available percentage <<< $(get_ram_usage)
            read python_ram node_ram ollama_ram <<< $(get_process_ram)
            echo "RAM Total: ${total}MB"
            echo "RAM Usada: ${used}MB (${percentage}%)"
            echo "RAM Disponible: ${available}MB"
            echo "Python: ${python_ram}MB"
            echo "Electron: ${node_ram}MB"
            echo "Ollama: ${ollama_ram}MB"
            exit 0
            ;;
        "--optimize")
            read total used available percentage <<< $(get_ram_usage)
            optimize_memory "$used" "$total" "$ALERT_THRESHOLD"
            exit 0
            ;;
        "--log")
            LOG_FILE="$2"
            shift 2
            ;;
        "--interval")
            CHECK_INTERVAL="$2"
            shift 2
            ;;
        *)
            if [[ "$1" =~ ^[0-9]+$ ]]; then
                ALERT_THRESHOLD="$1"
            fi
            ;;
    esac
    
    # Iniciar monitor
    monitor_loop
}

# Ejecutar
trap 'echo -e "\n${GREEN}[+] Monitor detenido${NC}"; exit 0' INT TERM
main "$@"