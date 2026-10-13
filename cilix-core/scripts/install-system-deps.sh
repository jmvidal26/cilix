#!/bin/bash

# Script para instalar dependencias del sistema para Cilix
# Compatible con Ubuntu/Debian y Fedora

set -e

print_info() {
    echo -e "\033[0;36m[i]\033[0m $1"
}

print_success() {
    echo -e "\033[0;32m[✓]\033[0m $1"
}

print_warning() {
    echo -e "\033[1;33m[!]\033[0m $1"
}

print_error() {
    echo -e "\033[0;31m[✗]\033[0m $1"
}

detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "$ID"
    elif command -v lsb_release &> /dev/null; then
        lsb_release -si | tr '[:upper:]' '[:lower:]'
    else
        echo "unknown"
    fi
}

install_debian_deps() {
    print_info "Instalando dependencias para Debian/Ubuntu..."
    
    sudo apt-get update
    
    # Dependencias de audio
    sudo apt-get install -y \
        python3-dev \
        portaudio19-dev \
        libasound2-dev \
        libjack-dev \
        ffmpeg \
        libavdevice-dev \
        libavfilter-dev \
        libavformat-dev \
        libavcodec-dev \
        libswresample-dev \
        libswscale-dev
    
    # Dependencias de visión
    sudo apt-get install -y \
        libopencv-dev \
        libgtk-3-dev \
        libcanberra-gtk3-module \
        libsm6 \
        libxext6 \
        libxrender-dev \
        libgl1-mesa-glx
    
    # Dependencias generales
    sudo apt-get install -y \
        build-essential \
        cmake \
        pkg-config \
        curl \
        wget \
        git \
        python3-venv \
        python3-pip
    
    print_success "Dependencias Debian/Ubuntu instaladas"
}

install_fedora_deps() {
    print_info "Instalando dependencias para Fedora..."
    
    sudo dnf update -y
    
    # Dependencias de audio
    sudo dnf install -y \
        python3-devel \
        portaudio-devel \
        alsa-lib-devel \
        jack-audio-connection-kit-devel \
        ffmpeg \
        ffmpeg-devel
    
    # Dependencias de visión
    sudo dnf install -y \
        opencv-devel \
        gtk3-devel \
        libcanberra-devel \
        libSM \
        libXext \
        libXrender \
        mesa-libGL
    
    # Dependencias generales
    sudo dnf install -y \
        gcc \
        gcc-c++ \
        make \
        cmake \
        curl \
        wget \
        git \
        python3-virtualenv \
        python3-pip
    
    print_success "Dependencias Fedora instaladas"
}

install_arch_deps() {
    print_info "Instalando dependencias para Arch Linux..."
    
    sudo pacman -Sy --noconfirm
    
    # Dependencias de audio
    sudo pacman -S --noconfirm \
        python-pip \
        portaudio \
        alsa-lib \
        jack2 \
        ffmpeg
    
    # Dependencias de visión
    sudo pacman -S --noconfirm \
        opencv \
        gtk3 \
        libcanberra \
        libsm \
        libxext \
        libxrender \
        mesa
    
    # Dependencias generales
    sudo pacman -S --noconfirm \
        base-devel \
        cmake \
        curl \
        wget \
        git
    
    print_success "Dependencias Arch Linux instaladas"
}

check_python_audio() {
    print_info "Verificando instalación de audio Python..."
    
    # Verificar que podemos importar módulos de audio
    python3 -c "
try:
    import sounddevice
    import soundfile
    import simpleaudio
    print('✅ Módulos de audio funcionando')
except ImportError as e:
    print(f'❌ Error: {e}')
    exit(1)
"
    
    if [ $? -eq 0 ]; then
        print_success "Audio Python verificado"
        return 0
    else
        print_error "Problemas con audio Python"
        return 1
    fi
}

main() {
    echo "=== Instalador de Dependencias del Sistema para Cilix ==="
    echo ""
    
    # Detectar distribución
    DISTRO=$(detect_distro)
    print_info "Distribución detectada: $DISTRO"
    
    # Instalar dependencias según distribución
    case "$DISTRO" in
        ubuntu|debian|linuxmint|pop)
            install_debian_deps
            ;;
        fedora|rhel|centos)
            install_fedora_deps
            ;;
        arch|manjaro|endeavouros)
            install_arch_deps
            ;;
        *)
            print_warning "Distribución no soportada: $DISTRO"
            print_info "Instala manualmente las dependencias de audio y visión"
            ;;
    esac
    
    # Verificar instalación
    if check_python_audio; then
        print_success "¡Todas las dependencias instaladas correctamente!"
        echo ""
        echo "📋 Resumen:"
        echo "  • Dependencias del sistema instaladas"
        echo "  • Audio Python funcionando"
        echo "  • Listo para instalar Cilix"
    else
        print_error "Hubo problemas con la instalación"
        echo ""
        echo "🔧 Solución:"
        echo "  1. Instala manualmente:"
        echo "     sudo apt install python3-dev portaudio19-dev"
        echo "  2. Reintenta: pip install sounddevice simpleaudio"
        exit 1
    fi
}

# Ejecutar
if [ "$(id -u)" -eq 0 ]; then
    print_warning "Ejecutando como root, cuidado con las instalaciones"
fi

main "$@"