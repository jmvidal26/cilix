#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════
#  Cilix · Habilita sudo SIN contraseña, pero SOLO para comandos de gestión
#  ═════───────────────────────────────────────────────────────────────────
#  El backend de Cilix ejecuta privilegios con `sudo -n` (nunca interactivo),
#  por lo que necesita que un conjunto ACOTADO de comandos no pida clave.
#
#  SEGURIDAD (doble capa):
#   1) Este script NO otorga NOPASSWD:ALL. Solo autoriza una lista blanca de
#      utilidades de administración (paquetes, servicios, logs, red, discos).
#      Cualquier otro binario bajo sudo seguirá exigiendo contraseña y, por
#      tanto, `sudo -n` fallará de forma segura.
#   2) En Python, `OSController._sudo_guard()` bloquea además los patrones
#      destructivos (rm -rf, mkfs, dd, chmod 777 /…) y las rutas protegidas,
#      así que ni siquiera llega a ejecutarse nada que tumbe el sistema.
#
#  Un borrado accidental de archivos de usuario se envía a la PAPELERA
#  (`gio trash`), nunca es definitivo.
#
#  Uso:   sudo bash scripts/cilix-sudo-setup.sh
#  Revierte: sudo rm -f /etc/sudoers.d/99-cilix
# ══════════════════════════════════════════════════════════════════════════
set -euo pipefail

SUDOERS_FILE="/etc/sudoers.d/99-cilix"
TARGET_USER="${SUDO_USER:-$(whoami)}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "❌ Este script debe ejecutarse como root:  sudo bash $0" >&2
  exit 1
fi

# Comandos de gestión autorizados sin contraseña. Se resuelven a rutas
# absolutas reales (apt puede vivir en /usr/bin u otra).
CMDS=(
  apt apt-get dpkg add-apt-repository
  systemctl journalctl loginctl hostnamectl timedatectl localectl
  nmcli networkctl
  lsblk blkid fdisk-partscan
  udisksctl
  dkms modprobe
  snap
)

# Construir la lista de rutas absolutas que existen en el sistema.
paths=""
for c in "${CMDS[@]}"; do
  p="$(command -v "$c" || true)"
  [[ -n "$p" ]] && paths+="$p, "
done
# Quitar la coma final
paths="${paths%, }"

if [[ -z "$paths" ]]; then
  echo "⚠️  No se encontró ningún binario de administración reconocido; abortando." >&2
  exit 1
fi

TMP="$(mktemp)"
{
  echo "# Generado por cilix-sudo-setup.sh — NOPASSWD acotado para Cilix"
  echo "# Borrar con: sudo rm -f $SUDOERS_FILE"
  echo "Defaults !requiretty"
  echo "$TARGET_USER ALL=(ALL) NOPASSWD: $paths"
} > "$TMP"

# Validar antes de instalar: una sudoers corrupto puede bloquear el sistema.
if visudo -c -f "$TMP" >/dev/null 2>&1; then
  install -m 0440 -o root -g root "$TMP" "$SUDOERS_FILE"
  echo "✅ sudo sin contraseña habilitado para '$TARGET_USER' (comandos de gestión)."
  echo "   Autorizados: ${paths//, /, }"
  echo "   Prueba:  sudo -n systemctl status --no-pager | head"
else
  echo "❌ La validación de sudoers falló; NO se modificó el sistema." >&2
  rm -f "$TMP"
  exit 1
fi
rm -f "$TMP"
