#!/usr/bin/env python3
"""
Sylix OS Core - Electron Python Integration Module

Este módulo proporciona integración entre el backend Python y la aplicación Electron.
Expone APIs adicionales para funcionalidades avanzadas de Linux.
"""

import asyncio
import json
import os
import sys
import subprocess
import threading
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
import psutil
import socket

# Configuración
CONFIG_PATH = os.path.expanduser("~/.config/sylix/config.json")
LOG_PATH = os.path.expanduser("~/.config/sylix/logs")

@dataclass
class SystemProcess:
    pid: int
    name: str
    cpu_percent: float
    memory_percent: float
    status: str
    cmdline: List[str]

@dataclass
class ServiceInfo:
    name: str
    description: str
    loaded: bool
    active: bool
    state: str

class LinuxSystemManager:
    """Gestor avanzado del sistema Linux para Sylix OS Core."""
    
    def __init__(self):
        self.config = self._load_config()
        self._setup_directories()
        
    def _load_config(self) -> Dict[str, Any]:
        """Carga la configuración desde el archivo."""
        default_config = {
            "system": {
                "monitor_interval": 5,
                "max_log_size": 10485760,  # 10MB
                "enable_remote_access": False,
                "allowed_commands": ["ls", "ps", "df", "free", "top", "htop", "nmap"]
            },
            "automation": {
                "enable_desktop_automation": True,
                "enable_file_operations": True,
                "enable_process_control": True
            }
        }
        
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, 'r') as f:
                    return {**default_config, **json.load(f)}
        except Exception:
            pass
        
        return default_config
    
    def _setup_directories(self):
        """Crea los directorios necesarios."""
        directories = [
            LOG_PATH,
            os.path.join(LOG_PATH, "commands"),
            os.path.join(LOG_PATH, "system"),
            os.path.expanduser("~/.sylix/scripts"),
            os.path.expanduser("~/.sylix/templates")
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
    
    async def get_system_info(self) -> Dict[str, Any]:
        """Obtiene información completa del sistema."""
        try:
            info = {
                "cpu": await self._get_cpu_info(),
                "memory": await self._get_memory_info(),
                "disk": await self._get_disk_info(),
                "network": await self._get_network_info(),
                "processes": await self._get_top_processes(10),
                "services": await self._get_service_status(),
                "users": await self._get_logged_in_users(),
                "uptime": await self._get_uptime(),
                "datetime": datetime.now().isoformat()
            }
            return info
        except Exception as e:
            return {"error": str(e)}
    
    async def _get_cpu_info(self) -> Dict[str, Any]:
        """Información de la CPU."""
        cpu_percent = psutil.cpu_percent(interval=1, percpu=True)
        cpu_freq = psutil.cpu_freq()
        cpu_count = psutil.cpu_count()
        
        return {
            "percent": cpu_percent,
            "percent_total": sum(cpu_percent) / len(cpu_percent) if cpu_percent else 0,
            "frequency_current": cpu_freq.current if cpu_freq else None,
            "frequency_min": cpu_freq.min if cpu_freq else None,
            "frequency_max": cpu_freq.max if cpu_freq else None,
            "cores_physical": psutil.cpu_count(logical=False),
            "cores_logical": cpu_count,
            "load_avg": os.getloadavg() if hasattr(os, 'getloadavg') else [0, 0, 0]
        }
    
    async def _get_memory_info(self) -> Dict[str, Any]:
        """Información de memoria."""
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        return {
            "total": mem.total,
            "available": mem.available,
            "used": mem.used,
            "percent": mem.percent,
            "swap_total": swap.total,
            "swap_used": swap.used,
            "swap_percent": swap.percent
        }
    
    async def _get_disk_info(self) -> List[Dict[str, Any]]:
        """Información de discos."""
        disks = []
        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                disks.append({
                    "device": partition.device,
                    "mountpoint": partition.mountpoint,
                    "fstype": partition.fstype,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent
                })
            except Exception:
                continue
        return disks
    
    async def _get_network_info(self) -> Dict[str, Any]:
        """Información de red."""
        net_io = psutil.net_io_counters()
        net_if = psutil.net_if_addrs()
        net_if_stats = psutil.net_if_stats()
        
        interfaces = {}
        for interface, addrs in net_if.items():
            stats = net_if_stats.get(interface, {})
            interfaces[interface] = {
                "addresses": [str(addr.address) for addr in addrs],
                "is_up": getattr(stats, 'isup', False),
                "speed": getattr(stats, 'speed', 0),
                "mtu": getattr(stats, 'mtu', 0)
            }
        
        return {
            "bytes_sent": net_io.bytes_sent,
            "bytes_recv": net_io.bytes_recv,
            "packets_sent": net_io.packets_sent,
            "packets_recv": net_io.packets_recv,
            "interfaces": interfaces
        }
    
    async def _get_top_processes(self, count: int = 10) -> List[Dict[str, Any]]:
        """Obtiene los procesos que más consumen recursos."""
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status', 'cmdline']):
            try:
                proc_info = proc.info
                processes.append({
                    "pid": proc_info['pid'],
                    "name": proc_info['name'],
                    "cpu_percent": proc_info['cpu_percent'] or 0,
                    "memory_percent": proc_info['memory_percent'] or 0,
                    "status": proc_info['status'],
                    "cmdline": proc_info['cmdline'] or []
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Ordenar por uso de CPU y memoria
        processes.sort(key=lambda p: (p['cpu_percent'], p['memory_percent']), reverse=True)
        return processes[:count]
    
    async def _get_service_status(self) -> List[Dict[str, Any]]:
        """Obtiene el estado de los servicios systemd."""
        services = []
        try:
            result = subprocess.run(
                ['systemctl', 'list-units', '--type=service', '--no-pager', '--plain'],
                capture_output=True, text=True, timeout=5
            )
            
            for line in result.stdout.strip().split('\n')[1:]:
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 4:
                        services.append({
                            "name": parts[0],
                            "loaded": parts[1] == 'loaded',
                            "active": parts[2] == 'active',
                            "state": parts[3],
                            "description": ' '.join(parts[4:]) if len(parts) > 4 else ''
                        })
        except Exception:
            pass
        
        return services
    
    async def _get_logged_in_users(self) -> List[Dict[str, Any]]:
        """Obtiene usuarios conectados."""
        users = []
        try:
            for user in psutil.users():
                users.append({
                    "name": user.name,
                    "terminal": user.terminal,
                    "host": user.host,
                    "started": user.started,
                    "pid": user.pid
                })
        except Exception:
            pass
        
        return users
    
    async def _get_uptime(self) -> Dict[str, Any]:
        """Obtiene el tiempo de actividad del sistema."""
        try:
            uptime_seconds = psutil.boot_time()
            uptime = datetime.now() - datetime.fromtimestamp(uptime_seconds)
            
            return {
                "seconds": int(uptime.total_seconds()),
                "days": uptime.days,
                "hours": uptime.seconds // 3600,
                "minutes": (uptime.seconds % 3600) // 60,
                "timestamp": uptime_seconds,
                "formatted": str(uptime)
            }
        except Exception:
            return {"seconds": 0, "formatted": "Unknown"}
    
    async def execute_privileged_command(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """
        Ejecuta un comando con privilegios elevados usando pkexec.
        
        Args:
            command: Comando a ejecutar
            timeout: Tiempo máximo de espera en segundos
        
        Returns:
            Resultado de la ejecución
        """
        log_file = os.path.join(LOG_PATH, "commands", f"cmd_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        
        try:
            # Prefijo con pkexec para privilegios gráficos en Pop!_OS
            full_command = f"pkexec {command}"
            
            result = subprocess.run(
                full_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            # Registrar en log
            with open(log_file, 'w') as f:
                f.write(f"COMMAND: {command}\n")
                f.write(f"TIMESTAMP: {datetime.now().isoformat()}\n")
                f.write(f"RETURNCODE: {result.returncode}\n")
                f.write(f"STDOUT:\n{result.stdout}\n")
                f.write(f"STDERR:\n{result.stderr}\n")
            
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "command": command,
                "log_file": log_file
            }
            
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Command timeout after {timeout} seconds",
                "command": command
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "command": command
            }
    
    async def manage_service(self, service_name: str, action: str) -> Dict[str, Any]:
        """
        Gestiona servicios systemd.
        
        Args:
            service_name: Nombre del servicio
            action: start, stop, restart, enable, disable, status
        
        Returns:
            Resultado de la operación
        """
        valid_actions = ['start', 'stop', 'restart', 'enable', 'disable', 'status']
        if action not in valid_actions:
            return {"success": False, "error": f"Invalid action: {action}"}
        
        try:
            command = f"systemctl {action} {service_name}"
            if action == 'status':
                command = f"systemctl status {service_name} --no-pager"
            
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "service": service_name,
                "action": action
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "service": service_name,
                "action": action
            }
    
    async def create_script(self, name: str, content: str, script_type: str = "bash") -> Dict[str, Any]:
        """
        Crea un script ejecutable.
        
        Args:
            name: Nombre del script (sin extensión)
            content: Contenido del script
            script_type: Tipo de script (bash, python, etc.)
        
        Returns:
            Información del script creado
        """
        scripts_dir = os.path.expanduser("~/.sylix/scripts")
        extensions = {
            "bash": ".sh",
            "python": ".py",
            "zsh": ".zsh",
            "fish": ".fish"
        }
        
        ext = extensions.get(script_type, ".sh")
        script_path = os.path.join(scripts_dir, f"{name}{ext}")
        
        try:
            with open(script_path, 'w') as f:
                if script_type == "bash":
                    f.write("#!/usr/bin/env bash\n")
                elif script_type == "python":
                    f.write("#!/usr/bin/env python3\n")
                f.write(content)
            
            # Hacer ejecutable
            os.chmod(script_path, 0o755)
            
            return {
                "success": True,
                "path": script_path,
                "name": name,
                "type": script_type,
                "executable": True
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "name": name,
                "type": script_type
            }
    
    async def get_system_logs(self, log_type: str = "syslog", lines: int = 100) -> Dict[str, Any]:
        """
        Obtiene logs del sistema.
        
        Args:
            log_type: Tipo de log (syslog, auth, kern, etc.)
            lines: Número de líneas a obtener
        
        Returns:
            Logs solicitados
        """
        log_files = {
            "syslog": "/var/log/syslog",
            "auth": "/var/log/auth.log",
            "kern": "/var/log/kern.log",
            "dpkg": "/var/log/dpkg.log",
            "apt": "/var/log/apt/history.log",
            "journal": "journalctl -n"
        }
        
        log_source = log_files.get(log_type, log_type)
        
        try:
            if log_type == "journal":
                result = subprocess.run(
                    f"{log_source} {lines}",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                content = result.stdout
            else:
                if not os.path.exists(log_source):
                    return {"success": False, "error": f"Log file not found: {log_source}"}
                
                result = subprocess.run(
                    f"tail -n {lines} {log_source}",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                content = result.stdout
            
            return {
                "success": True,
                "type": log_type,
                "source": log_source,
                "lines": lines,
                "content": content
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "type": log_type
            }


# API WebSocket adicional para funcionalidades de Linux
class LinuxWebSocketAPI:
    """API WebSocket para funcionalidades avanzadas de Linux."""
    
    def __init__(self):
        self.system_manager = LinuxSystemManager()
        self.connections = {}
    
    async def handle_message(self, message: Dict[str, Any], websocket) -> Dict[str, Any]:
        """
        Maneja mensajes WebSocket para funcionalidades de Linux.
        
        Args:
            message: Mensaje recibido
            websocket: Conexión WebSocket
        
        Returns:
            Respuesta al mensaje
        """
        msg_type = message.get("type", "")
        data = message.get("data", {})
        
        handlers = {
            "system_info": self._handle_system_info,
            "execute_privileged": self._handle_execute_privileged,
            "manage_service": self._handle_manage_service,
            "create_script": self._handle_create_script,
            "get_logs": self._handle_get_logs,
            "monitor_start": self._handle_monitor_start,
            "monitor_stop": self._handle_monitor_stop
        }
        
        handler = handlers.get(msg_type)
        if handler:
            return await handler(data, websocket)
        else:
            return {"type": "error", "error": f"Unknown message type: {msg_type}"}
    
    async def _handle_system_info(self, data: Dict[str, Any], websocket) -> Dict[str, Any]:
        """Maneja solicitud de información del sistema."""
        try:
            info = await self.system_manager.get_system_info()
            return {
                "type": "system_info",
                "data": info,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"type": "error", "error": str(e)}
    
    async def _handle_execute_privileged(self, data: Dict[str, Any], websocket) -> Dict[str, Any]:
        """Maneja ejecución de comandos privilegiados."""
        command = data.get("command", "")
        timeout = data.get("timeout", 30)
        
        if not command:
            return {"type": "error", "error": "No command provided"}
        
        result = await self.system_manager.execute_privileged_command(command, timeout)
        return {
            "type": "command_result",
            "data": result,
            "timestamp": datetime.now().isoformat()
        }
    
    async def _handle_manage_service(self, data: Dict[str, Any], websocket) -> Dict[str, Any]:
        """Maneja gestión de servicios."""
        service = data.get("service", "")
        action = data.get("action", "")
        
        if not service or not action:
            return {"type": "error", "error": "Service name and action required"}
        
        result = await self.system_manager.manage_service(service, action)
        return {
            "type": "service_result",
            "data": result,
            "timestamp": datetime.now().isoformat()
        }
    
    async def _handle_create_script(self, data: Dict[str, Any], websocket) -> Dict[str, Any]:
        """Maneja creación de scripts."""
        name = data.get("name", "")
        content = data.get("content", "")
        script_type = data.get("type", "bash")
        
        if not name or not content:
            return {"type": "error", "error": "Script name and content required"}
        
        result = await self.system_manager.create_script(name, content, script_type)
        return {
            "type": "script_created",
            "data": result,
            "timestamp": datetime.now().isoformat()
        }
    
    async def _handle_get_logs(self, data: Dict[str, Any], websocket) -> Dict[str, Any]:
        """Maneja obtención de logs."""
        log_type = data.get("type", "syslog")
        lines = data.get("lines", 100)
        
        result = await self.system_manager.get_system_logs(log_type, lines)
        return {
            "type": "system_logs",
            "data": result,
            "timestamp": datetime.now().isoformat()
        }
    
    async def _handle_monitor_start(self, data: Dict[str, Any], websocket) -> Dict[str, Any]:
        """Inicia monitoreo en tiempo real."""
        interval = data.get("interval", 5)
        client_id = data.get("client_id", "")
        
        if client_id:
            self.connections[client_id] = {
                "websocket": websocket,
                "monitoring": True,
                "interval": interval
            }
            
            # Iniciar loop de monitoreo
            asyncio.create_task(self._monitoring_loop(client_id, interval))
            
            return {
                "type": "monitor_started",
                "data": {"interval": interval, "client_id": client_id}
            }
        
        return {"type": "error", "error": "Client ID required"}
    
    async def _handle_monitor_stop(self, data: Dict[str, Any], websocket) -> Dict[str, Any]:
        """Detiene monitoreo."""
        client_id = data.get("client_id", "")
        
        if client_id in self.connections:
            self.connections[client_id]["monitoring"] = False
            del self.connections[client_id]
            
            return {
                "type": "monitor_stopped",
                "data": {"client_id": client_id}
            }
        
        return {"type": "error", "error": "Client not found"}
    
    async def _monitoring_loop(self, client_id: str, interval: int):
        """Loop de monitoreo en tiempo real."""
        while client_id in self.connections and self.connections[client_id]["monitoring"]:
            try:
                info = await self.system_manager.get_system_info()
                
                message = {
                    "type": "monitor_update",
                    "data": info,
                    "timestamp": datetime.now().isoformat()
                }
                
                await self.connections[client_id]["websocket"].send(json.dumps(message))
                await asyncio.sleep(interval)
                
            except Exception as e:
                if client_id in self.connections:
                    self.connections[client_id]["monitoring"] = False
                break


# Inicialización y ejecución
async def main():
    """Función principal para pruebas."""
    manager = LinuxSystemManager()
    
    print("Sylix OS Core - Linux System Manager")
    print("=" * 50)
    
    # Obtener información del sistema
    info = await manager.get_system_info()
    print(f"System Info: {json.dumps(info, indent=2, default=str)}")
    
    # Probar creación de script
    script_result = await manager.create_script(
        "test_script",
        "echo 'Hello from Sylix OS Core!'\ndate\nwhoami",
        "bash"
    )
    print(f"Script Created: {script_result}")

if __name__ == "__main__":
    asyncio.run(main())