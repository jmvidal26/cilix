#!/usr/bin/env python3
"""
Controlador del Sistema Operativo para Cilix
Ejecución segura de comandos y control local
Protege contra comandos peligrosos
"""

import asyncio
import json
import logging
import os
import re
import shlex
import subprocess
import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

class CommandType(Enum):
    """Tipos de comandos permitidos"""
    FILE_OPERATION = "file_operation"
    APP_LAUNCH = "app_launch"
    SYSTEM_INFO = "system_info"
    SHELL_COMMAND = "shell_command"
    CUSTOM_SCRIPT = "custom_script"

class CommandSafety(Enum):
    """Niveles de seguridad de comandos"""
    SAFE = "safe"           # Comandos totalmente seguros
    RESTRICTED = "restricted"  # Comandos con precauciones
    DANGEROUS = "dangerous"  # Comandos potencialmente peligrosos
    BLOCKED = "blocked"     # Comandos completamente bloqueados

@dataclass
class CommandResult:
    """Resultado de ejecución de comando"""
    success: bool
    output: str
    error: str
    exit_code: int
    duration: float
    command: str

@dataclass
class SystemInfo:
    """Información del sistema"""
    os_name: str
    os_version: str
    architecture: str
    total_ram_mb: float
    available_ram_mb: float
    cpu_count: int
    cpu_usage: float
    disk_usage: Dict[str, float]
    username: str
    hostname: str

class OSController:
    """
    Controlador seguro del sistema operativo para Cilix
    Ejecuta comandos locales con validación y límites de seguridad
    """
    
    def __init__(self, allowed_paths: Optional[List[str]] = None):
        # Directorios permitidos para operaciones
        self.allowed_paths = allowed_paths or [
            str(Path.home()),  # Directorio home del usuario
            "/tmp",
            "/var/tmp"
        ]
        
        # Comandos permitidos (lista blanca)
        self.allowed_commands = {
            # Comandos de archivos (seguros)
            "ls": CommandSafety.SAFE,
            "cat": CommandSafety.SAFE,
            "file": CommandSafety.SAFE,
            "stat": CommandSafety.SAFE,
            "find": CommandSafety.RESTRICTED,
            "grep": CommandSafety.SAFE,
            "wc": CommandSafety.SAFE,
            
            # Información del sistema
            "date": CommandSafety.SAFE,
            "uptime": CommandSafety.SAFE,
            "whoami": CommandSafety.SAFE,
            "uname": CommandSafety.SAFE,
            "df": CommandSafety.SAFE,
            "free": CommandSafety.SAFE,
            
            # Aplicaciones comunes (Linux)
            "xdg-open": CommandSafety.SAFE,  # Abrir archivos
            "nautilus": CommandSafety.SAFE,   # Nautilus
            "gedit": CommandSafety.SAFE,      # Editor de texto
            "firefox": CommandSafety.SAFE,    # Navegador
            "chromium": CommandSafety.SAFE,   # Navegador
            "code": CommandSafety.SAFE,       # VS Code
            "python3": CommandSafety.RESTRICTED,
            "node": CommandSafety.RESTRICTED,
        }
        
        # Comandos bloqueados (lista negra)
        self.blocked_commands = {
            # Destructivos
            "rm": CommandSafety.BLOCKED,
            "rmdir": CommandSafety.BLOCKED,
            "del": CommandSafety.BLOCKED,
            "format": CommandSafety.BLOCKED,
            "dd": CommandSafety.BLOCKED,
            
            # Privilegiados
            "sudo": CommandSafety.BLOCKED,
            "su": CommandSafety.BLOCKED,
            "chmod": CommandSafety.BLOCKED,
            "chown": CommandSafety.BLOCKED,
            "passwd": CommandSafety.BLOCKED,
            
            # Red y sistema
            "shutdown": CommandSafety.BLOCKED,
            "reboot": CommandSafety.BLOCKED,
            "halt": CommandSafety.BLOCKED,
            "ifconfig": CommandSafety.BLOCKED,
            "iptables": CommandSafety.BLOCKED,
            
            # Shells y scripting peligroso
            "bash": CommandSafety.BLOCKED,
            "sh": CommandSafety.BLOCKED,
            "zsh": CommandSafety.BLOCKED,
            "python": CommandSafety.BLOCKED,  # python sin restricciones
            "perl": CommandSafety.BLOCKED,
        }
        
        # Patrones peligrosos
        self.dangerous_patterns = [
            r"rm\s+-[rf]",          # rm -rf
            r":(){:|:&};:",        # Fork bomb
            r"mv\s+/\s+",          # mover root
            r"chmod\s+[0-7]{3,4}", # chmod peligroso
            r">\s+/dev/",          # redirección a dispositivos
            r"\|\s*bash\s*$",      # pipe a bash
            r"\$\(.*\)",           # subprocess en shell
            r"`.*`",               # backticks
        ]
        
        # Límites de seguridad
        self.security_limits = {
            "max_command_length": 1000,
            "max_output_size": 1024 * 1024,  # 1MB
            "max_execution_time": 30,        # 30 segundos
            "max_processes": 3,
            "allowed_env_vars": ["PATH", "HOME", "USER", "LANG"]
        }
        
        # Estadísticas
        self.stats = {
            "commands_executed": 0,
            "commands_blocked": 0,
            "safe_commands": 0,
            "restricted_commands": 0,
            "total_execution_time": 0.0
        }
        
        # Cache de aplicaciones instaladas
        self.installed_apps_cache = None
        self.cache_timeout = 300  # 5 minutos
        
        logger.info("🛡️ OSController inicializado")
        
    def _classify_command(self, command: str) -> Tuple[CommandSafety, str]:
        """
        Clasificar comando por seguridad
        
        Args:
            command: Comando a clasificar
            
        Returns:
            Tupla (seguridad, razón)
        """
        # Limpiar y analizar comando
        clean_cmd = command.strip()
        
        # Verificar longitud
        if len(clean_cmd) > self.security_limits["max_command_length"]:
            return CommandSafety.BLOCKED, "Comando demasiado largo"
            
        # Buscar patrones peligrosos
        for pattern in self.dangerous_patterns:
            if re.search(pattern, clean_cmd, re.IGNORECASE):
                return CommandSafety.BLOCKED, f"Patrón peligroso detectado: {pattern}"
                
        # Extraer comando base (primer token)
        try:
            parts = shlex.split(clean_cmd)
            if not parts:
                return CommandSafety.BLOCKED, "Comando vacío"
                
            base_cmd = parts[0].lower()
            
            # Verificar comandos bloqueados
            if base_cmd in self.blocked_commands:
                safety = self.blocked_commands[base_cmd]
                return safety, f"Comando en lista negra: {base_cmd}"
                
            # Verificar comandos permitidos
            if base_cmd in self.allowed_commands:
                safety = self.allowed_commands[base_cmd]
                return safety, f"Comando en lista blanca: {base_cmd}"
                
            # Comando desconocido - restringido por defecto
            return CommandSafety.RESTRICTED, f"Comando desconocido: {base_cmd}"
            
        except ValueError:
            return CommandSafety.BLOCKED, "Sintaxis de comando inválida"
            
    def _sanitize_command(self, command: str) -> str:
        """
        Sanitizar comando para mayor seguridad
        
        Args:
            command: Comando original
            
        Returns:
            Comando sanitizado
        """
        # Eliminar caracteres peligrosos
        dangerous_chars = [';', '&', '|', '`', '$', '(', ')', '{', '}', '[', ']']
        
        sanitized = command
        for char in dangerous_chars:
            sanitized = sanitized.replace(char, '')
            
        # Limitar longitud
        if len(sanitized) > self.security_limits["max_command_length"]:
            sanitized = sanitized[:self.security_limits["max_command_length"]]
            
        return sanitized.strip()
        
    def _is_path_allowed(self, path: str) -> bool:
        """
        Verificar si una ruta está permitida
        
        Args:
            path: Ruta a verificar
            
        Returns:
            True si la ruta está permitida
        """
        try:
            abs_path = os.path.abspath(path)
            
            for allowed_path in self.allowed_paths:
                allowed_abs = os.path.abspath(allowed_path)
                
                # Verificar si la ruta está dentro de un directorio permitido
                if abs_path.startswith(allowed_abs):
                    return True
                    
            return False
            
        except Exception:
            return False
            
    async def execute_safe_command(self, command: str, cwd: Optional[str] = None) -> CommandResult:
        """
        Ejecutar comando con validación de seguridad
        
        Args:
            command: Comando a ejecutar
            cwd: Directorio de trabajo (opcional)
            
        Returns:
            Resultado de la ejecución
        """
        start_time = time.time()
        
        try:
            # Validar y clasificar comando
            safety, reason = self._classify_command(command)
            
            if safety == CommandSafety.BLOCKED:
                self.stats["commands_blocked"] += 1
                logger.warning(f"🚫 Comando bloqueado: {reason}")
                
                return CommandResult(
                    success=False,
                    output="",
                    error=f"Comando bloqueado por seguridad: {reason}",
                    exit_code=1,
                    duration=time.time() - start_time,
                    command=command
                )
                
            # Sanitizar comando para comandos restringidos
            if safety == CommandSafety.RESTRICTED:
                command = self._sanitize_command(command)
                logger.info(f"⚠️ Comando restringido, sanitizado: {command}")
                self.stats["restricted_commands"] += 1
            else:
                self.stats["safe_commands"] += 1
                
            # Validar directorio de trabajo
            if cwd and not self._is_path_allowed(cwd):
                cwd = None
                
            # Preparar entorno seguro
            env = self._create_safe_environment()
            
            logger.info(f"▶️ Ejecutando comando ({safety.value}): {command}")
            
            # Ejecutar comando con límites
            result = await self._execute_with_limits(command, cwd, env)
            
            # Actualizar estadísticas
            self.stats["commands_executed"] += 1
            duration = time.time() - start_time
            self.stats["total_execution_time"] += duration
            
            # Actualizar duración en resultado
            result.duration = duration
            
            logger.info(f"✅ Comando ejecutado en {duration:.2f}s (exit: {result.exit_code})")
            
            return result
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"❌ Error ejecutando comando: {e}")
            
            return CommandResult(
                success=False,
                output="",
                error=f"Error interno: {str(e)}",
                exit_code=-1,
                duration=duration,
                command=command
            )
            
    async def _execute_with_limits(self, command: str, cwd: Optional[str], env: Dict) -> CommandResult:
        """
        Ejecutar comando con límites de recursos
        
        Args:
            command: Comando a ejecutar
            cwd: Directorio de trabajo
            env: Variables de entorno
            
        Returns:
            Resultado de la ejecución
        """
        try:
            # Preparar proceso
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                limit=self.security_limits["max_output_size"]
            )
            
            # Ejecutar con timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.security_limits["max_execution_time"]
                )
                
                # Decodificar salida
                output = stdout.decode('utf-8', errors='ignore') if stdout else ""
                error = stderr.decode('utf-8', errors='ignore') if stderr else ""
                
                return CommandResult(
                    success=process.returncode == 0,
                    output=output.strip(),
                    error=error.strip(),
                    exit_code=process.returncode,
                    duration=0.0,  # Se actualizará después
                    command=command
                )
                
            except asyncio.TimeoutError:
                # Terminar proceso por timeout
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    
                return CommandResult(
                    success=False,
                    output="",
                    error=f"Timeout: Comando excedió {self.security_limits['max_execution_time']} segundos",
                    exit_code=-2,
                    duration=self.security_limits["max_execution_time"],
                    command=command
                )
                
        except Exception as e:
            return CommandResult(
                success=False,
                output="",
                error=f"Error al ejecutar: {str(e)}",
                exit_code=-1,
                duration=0.0,
                command=command
            )
            
    def _create_safe_environment(self) -> Dict[str, str]:
        """
        Crear entorno de ejecución seguro
        
        Returns:
            Diccionario con variables de entorno
        """
        # Variables de entorno base
        safe_env = os.environ.copy()
        
        # Filtrar variables peligrosas
        allowed_vars = self.security_limits["allowed_env_vars"]
        filtered_env = {}
        
        for var in allowed_vars:
            if var in safe_env:
                filtered_env[var] = safe_env[var]
                
        # Agregar variables seguras necesarias
        filtered_env["PATH"] = "/usr/bin:/bin:/usr/local/bin"
        filtered_env["HOME"] = str(Path.home())
        filtered_env["USER"] = os.environ.get("USER", "user")
        filtered_env["LANG"] = os.environ.get("LANG", "en_US.UTF-8")
        
        return filtered_env
        
    async def launch_application(self, app_name: str, arguments: List[str] = None) -> CommandResult:
        """
        Lanzar aplicación de forma segura
        
        Args:
            app_name: Nombre de la aplicación
            arguments: Argumentos adicionales
            
        Returns:
            Resultado del lanzamiento
        """
        try:
            # Verificar si la aplicación está instalada
            installed_apps = await self.get_installed_applications()
            
            if app_name not in installed_apps:
                return CommandResult(
                    success=False,
                    output="",
                    error=f"Aplicación no encontrada: {app_name}",
                    exit_code=1,
                    duration=0.0,
                    command=app_name
                )
                
            # Construir comando
            cmd_parts = [app_name]
            if arguments:
                # Sanitizar argumentos
                safe_args = [self._sanitize_command(arg) for arg in arguments]
                cmd_parts.extend(safe_args)
                
            command = " ".join(cmd_parts)
            
            # Ejecutar comando en background
            result = await self.execute_safe_command(f"{command} &")
            
            if result.success:
                logger.info(f"🚀 Aplicación lanzada: {app_name}")
                
            return result
            
        except Exception as e:
            logger.error(f"❌ Error lanzando aplicación: {e}")
            
            return CommandResult(
                success=False,
                output="",
                error=f"Error lanzando aplicación: {str(e)}",
                exit_code=-1,
                duration=0.0,
                command=app_name
            )
            
    async def get_installed_applications(self) -> List[str]:
        """
        Obtener lista de aplicaciones instaladas (con cache)
        
        Returns:
            Lista de nombres de aplicaciones
        """
        # Verificar cache
        current_time = time.time()
        if (self.installed_apps_cache and 
            current_time - self.installed_apps_cache["timestamp"] < self.cache_timeout):
            return self.installed_apps_cache["apps"]
            
        try:
            # Método para Linux: usar which y verificar binarios comunes
            common_apps = [
                "nautilus", "gedit", "firefox", "chromium", "code",
                "vlc", "gimp", "libreoffice", "thunderbird", "terminal",
                "gnome-terminal", "konsole", "xterm"
            ]
            
            installed = []
            
            for app in common_apps:
                result = await self.execute_safe_command(f"which {app}")
                if result.success and result.output:
                    installed.append(app)
                    
            # Cachear resultados
            self.installed_apps_cache = {
                "apps": installed,
                "timestamp": current_time
            }
            
            logger.info(f"📦 Aplicaciones detectadas: {len(installed)}")
            return installed
            
        except Exception as e:
            logger.error(f"❌ Error detectando aplicaciones: {e}")
            return []
            
    async def get_system_info(self) -> SystemInfo:
        """
        Obtener información del sistema
        
        Returns:
            Información del sistema
        """
        try:
            # Obtener información básica
            hostname_result = await self.execute_safe_command("hostname")
            username_result = await self.execute_safe_command("whoami")
            uname_result = await self.execute_safe_command("uname -a")
            
            # Obtener información de RAM
            ram_result = await self.execute_safe_command("free -m")
            ram_lines = ram_result.output.split('\n')
            total_ram = 0
            available_ram = 0
            
            if len(ram_lines) > 1:
                mem_line = ram_lines[1].split()
                if len(mem_line) >= 7:
                    total_ram = float(mem_line[1])
                    available_ram = float(mem_line[6])
                    
            # Obtener uso de CPU
            cpu_result = await self.execute_safe_command("top -bn1 | grep 'Cpu(s)'")
            cpu_usage = 0.0
            
            if cpu_result.success and cpu_result.output:
                # Extraer porcentaje de uso
                match = re.search(r'(\d+\.\d+)%?id', cpu_result.output)
                if match:
                    idle = float(match.group(1))
                    cpu_usage = 100.0 - idle
                    
            # Obtener uso de disco
            disk_result = await self.execute_safe_command("df -h /")
            disk_usage = {}
            
            if disk_result.success and disk_result.output:
                lines = disk_result.output.split('\n')
                if len(lines) > 1:
                    parts = lines[1].split()
                    if len(parts) >= 5:
                        disk_usage["/"] = float(parts[4].replace('%', ''))
                        
            return SystemInfo(
                os_name=platform.system(),
                os_version=platform.release(),
                architecture=platform.machine(),
                total_ram_mb=total_ram,
                available_ram_mb=available_ram,
                cpu_count=os.cpu_count() or 1,
                cpu_usage=cpu_usage,
                disk_usage=disk_usage,
                username=username_result.output.strip(),
                hostname=hostname_result.output.strip()
            )
            
        except Exception as e:
            logger.error(f"❌ Error obteniendo información del sistema: {e}")
            
            # Información básica de fallback
            return SystemInfo(
                os_name=platform.system(),
                os_version=platform.release(),
                architecture=platform.machine(),
                total_ram_mb=0,
                available_ram_mb=0,
                cpu_count=os.cpu_count() or 1,
                cpu_usage=0.0,
                disk_usage={},
                username=os.environ.get("USER", "unknown"),
                hostname="unknown"
            )
            
    def get_stats(self) -> Dict[str, Any]:
        """Obtener estadísticas del controlador"""
        return self.stats.copy()
        
    def cleanup(self):
        """Limpiar recursos"""
        # Limpiar cache
        self.installed_apps_cache = None
        logger.info("🧹 OSController limpiado")

# Función de prueba
async def test_os_controller():
    """Probar OSController"""
    print("🧪 Probando OSController...")
    
    controller = OSController()
    
    # Probar comandos seguros
    print("\n✅ Probando comandos seguros:")
    
    # Comando seguro
    result = await controller.execute_safe_command("date")
    print(f"  date: {'✅' if result.success else '❌'} - {result.output}")
    
    # Comando informativo
    result = await controller.execute_safe_command("whoami")
    print(f"  whoami: {'✅' if result.success else '❌'} - {result.output}")
    
    # Probar comando bloqueado
    print("\n🚫 Probando comando bloqueado:")
    result = await controller.execute_safe_command("rm -rf /")
    print(f"  rm -rf /: {'✅ Bloqueado' if not result.success else '❌ Permitido'}")
    
    # Probar información del sistema
    print("\n💻 Probando información del sistema:")
    sys_info = await controller.get_system_info()
    print(f"  OS: {sys_info.os_name} {sys_info.os_version}")
    print(f"  Hostname: {sys_info.hostname}")
    print(f"  Username: {sys_info.username}")
    print(f"  CPU Cores: {sys_info.cpu_count}")
    print(f"  RAM: {sys_info.total_ram_mb:.0f} MB total, {sys_info.available_ram_mb:.0f} MB disponible")
    
    # Estadísticas
    print("\n📊 Estadísticas:")
    stats = controller.get_stats()
    print(f"  Comandos ejecutados: {stats['commands_executed']}")
    print(f"  Comandos bloqueados: {stats['commands_blocked']}")
    print(f"  Comandos seguros: {stats['safe_commands']}")
    print(f"  Comandos restringidos: {stats['restricted_commands']}")
    
    # Limpiar
    controller.cleanup()
    print("\n✅ Pruebas completadas")

if __name__ == "__main__":
    asyncio.run(test_os_controller())