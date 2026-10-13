"""
activity_monitor.py — Monitor de Actividad del Usuario para Sylix OS Core

Características:
1. Monitorización de ventanas activas
2. Seguimiento de aplicaciones usadas
3. Análisis de patrones de uso
4. Detección de cambios de contexto
5. Registro de actividad para proactividad
"""

import os
import json
import time
import threading
import subprocess
import psutil
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging
from collections import defaultdict, deque
import platform

logger = logging.getLogger("sylix.activity")

# Configuración
ACTIVITY_DB_PATH = os.path.expanduser("~/.config/sylix/activity.db")
ACTIVITY_LOG_DIR = os.path.expanduser("~/.config/sylix/activity_logs")
MONITOR_INTERVAL = 5  # segundos entre capturas
MAX_HISTORY_DAYS = 7  # días de historial guardados

# Tipos de actividad
class ActivityType(Enum):
    WINDOW_FOCUS = "window_focus"
    APPLICATION_USE = "application_use"
    SYSTEM_EVENT = "system_event"
    USER_INTERACTION = "user_interaction"
    CONTEXT_CHANGE = "context_change"

@dataclass
class ActivityEvent:
    """Evento de actividad registrado."""
    id: str
    activity_type: ActivityType
    timestamp: datetime
    data: Dict[str, Any]
    duration: float = 0.0  # duración en segundos
    importance: float = 0.3
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "activity_type": self.activity_type.value,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
            "duration": self.duration,
            "importance": self.importance
        }

@dataclass
class ApplicationUsage:
    """Estadísticas de uso de aplicación."""
    name: str
    total_time: float = 0.0  # segundos totales
    sessions: int = 0
    last_used: Optional[datetime] = None
    frequency: float = 0.0  # veces por hora
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "total_time": self.total_time,
            "sessions": int(self.total_time / 3600),  # horas
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "frequency": self.frequency
        }

class ActivityMonitor:
    """Monitor principal de actividad del sistema."""
    
    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self.is_monitoring = False
        self.monitor_thread = None
        self.activity_buffer = deque(maxlen=1000)  # Buffer en memoria
        
        # Estadísticas
        self.current_window = None
        self.current_application = None
        self.window_start_time = None
        self.application_usage = {}  # nombre -> ApplicationUsage
        
        # Configuración
        self.db_path = ACTIVITY_DB_PATH
        self.log_dir = ACTIVITY_LOG_DIR
        
        # Crear directorios
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        os.makedirs(self.log_dir, exist_ok=True)
        
        # Inicializar base de datos
        self._init_database()
        
        # Cargar historial reciente
        self._load_recent_activity()
        
        logger.info(f"Activity Monitor inicializado (enabled={self.enabled})")
    
    def _init_database(self):
        """Inicializar base de datos para actividad."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Tabla de actividad
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS activity_events (
                    id TEXT PRIMARY KEY,
                    activity_type TEXT,
                    timestamp TEXT,
                    data TEXT,
                    duration REAL,
                    importance REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Tabla de estadísticas de aplicaciones
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS app_usage (
                    app_name TEXT PRIMARY KEY,
                    total_time REAL,
                    sessions INTEGER,
                    last_used TEXT,
                    frequency REAL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Tabla de patrones diarios
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_patterns (
                    date TEXT,
                    hour INTEGER,
                    activity_type TEXT,
                    count INTEGER,
                    total_duration REAL,
                    PRIMARY KEY (date, hour, activity_type)
                )
            ''')
            
            # Índices
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON activity_events(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_type ON activity_events(activity_type)')
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error initializing activity database: {e}")
    
    def _load_recent_activity(self):
        """Cargar actividad reciente desde la base de datos."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Cargar últimas 100 actividades
            cursor.execute(
                'SELECT * FROM activity_events '
                'ORDER BY timestamp DESC LIMIT 100'
            )
            
            for row in cursor.fetchall():
                try:
                    event = ActivityEvent(
                        id=row[0],
                        activity_type=ActivityType(row[1]),
                        timestamp=datetime.fromisoformat(row[2]),
                        data=json.loads(row[3]),
                        duration=row[4],
                        importance=row[5]
                    )
                    self.activity_buffer.append(event)
                except Exception as e:
                    logger.error(f"Error parsing activity event: {e}")
            
            # Cargar estadísticas de aplicaciones
            cursor.execute('SELECT * FROM app_usage')
            for row in cursor.fetchall():
                self.application_usage[row[0]] = ApplicationUsage(
                    name=row[0],
                    total_time=row[1],
                    sessions=row[2],
                    last_used=datetime.fromisoformat(row[3]) if row[3] else None,
                    frequency=row[4]
                )
            
            conn.close()
            
            logger.debug(f"Loaded {len(self.activity_buffer)} recent activities")
            
        except Exception as e:
            logger.error(f"Error loading recent activity: {e}")
    
    # ─── Métodos de Captura de Actividad ───────────────────────────────────────
    
    def get_active_window_info(self) -> Optional[Dict[str, Any]]:
        """Obtener información de la ventana activa."""
        try:
            system = platform.system().lower()
            
            if system == "linux":
                # Usar xdotool para Linux
                result = subprocess.run(
                    ['xdotool', 'getwindowfocus', 'getwindowname'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                
                if result.returncode == 0:
                    window_title = result.stdout.strip()
                    
                    # Intentar obtener clase de ventana
                    try:
                        class_result = subprocess.run(
                            ['xdotool', 'getwindowfocus', 'getwindowclassname'],
                            capture_output=True,
                            text=True,
                            timeout=1
                        )
                        window_class = class_result.stdout.strip() if class_result.returncode == 0 else "unknown"
                    except:
                        window_class = "unknown"
                    
                    return {
                        "title": window_title,
                        "class": window_class,
                        "system": "linux",
                        "timestamp": datetime.now().isoformat()
                    }
            
            elif system == "windows":
                # Windows - placeholder
                return {
                    "title": "Windows System",
                    "class": "windows",
                    "system": "windows",
                    "timestamp": datetime.now().isoformat()
                }
            
            elif system == "darwin":
                # macOS - placeholder
                return {
                    "title": "macOS System",
                    "class": "macos",
                    "system": "darwin",
                    "timestamp": datetime.now().isoformat()
                }
            
        except Exception as e:
            logger.debug(f"Error getting active window: {e}")
        
        return None
    
    def get_system_activity(self) -> Dict[str, Any]:
        """Obtener actividad del sistema."""
        try:
            # CPU y memoria
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            
            # Procesos activos
            process_count = len(psutil.pids())
            
            # Disco
            disk_io = psutil.disk_io_counters()
            disk_read = disk_io.read_bytes if disk_io else 0
            disk_write = disk_io.write_bytes if disk_io else 0
            
            # Red
            net_io = psutil.net_io_counters()
            net_sent = net_io.bytes_sent if net_io else 0
            net_recv = net_io.bytes_recv if net_io else 0
            
            # Usuarios conectados
            users = len(psutil.users())
            
            return {
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "process_count": process_count,
                "disk_read_bytes": disk_read,
                "disk_write_bytes": disk_write,
                "network_sent_bytes": net_sent,
                "network_recv_bytes": net_recv,
                "users_connected": users,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting system activity: {e}")
            return {"error": str(e)}
    
    def detect_context_change(self, old_window: Optional[Dict], new_window: Optional[Dict]) -> bool:
        """Detectar cambio de contexto basado en ventana activa."""
        if not old_window or not new_window:
            return True
        
        # Comparar título y clase de ventana
        if old_window.get("title") != new_window.get("title"):
            return True
        
        if old_window.get("class") != new_window.get("class"):
            return True
        
        return False
    
    # ─── Métodos de Registro de Actividad ──────────────────────────────────────
    
    def log_window_focus(self, window_info: Dict[str, Any], duration: float = 0.0):
        """Registrar cambio de foco de ventana."""
        if not self.enabled:
            return
        
        event_id = f"window_{int(time.time())}_{hash(str(window_info)) % 10000}"
        
        event = ActivityEvent(
            id=event_id,
            activity_type=ActivityType.WINDOW_FOCUS,
            timestamp=datetime.now(),
            data=window_info,
            duration=duration,
            importance=0.4
        )
        
        self._save_activity(event)
        
        # Actualizar estadísticas de aplicación
        app_name = window_info.get("class", "unknown")
        if app_name != "unknown":
            self._update_app_usage(app_name, duration)
    
    def log_application_use(self, app_name: str, action: str, details: Dict[str, Any] = None):
        """Registrar uso de aplicación específico."""
        if not self.enabled:
            return
        
        event_id = f"app_{int(time.time())}_{hash(app_name) % 10000}"
        
        event = ActivityEvent(
            id=event_id,
            activity_type=ActivityType.APPLICATION_USE,
            timestamp=datetime.now(),
            data={
                "application": app_name,
                "action": action,
                "details": details or {}
            },
            importance=0.5
        )
        
        self._save_activity(event)
    
    def log_system_event(self, event_type: str, details: Dict[str, Any]):
        """Registrar evento del sistema."""
        if not self.enabled:
            return
        
        event_id = f"sys_{int(time.time())}_{hash(event_type) % 10000}"
        
        event = ActivityEvent(
            id=event_id,
            activity_type=ActivityType.SYSTEM_EVENT,
            timestamp=datetime.now(),
            data={
                "event_type": event_type,
                "details": details
            },
            importance=0.6
        )
        
        self._save_activity(event)
    
    def log_user_interaction(self, interaction_type: str, details: Dict[str, Any]):
        """Registrar interacción del usuario."""
        if not self.enabled:
            return
        
        event_id = f"user_{int(time.time())}_{hash(interaction_type) % 10000}"
        
        event = ActivityEvent(
            id=event_id,
            activity_type=ActivityType.USER_INTERACTION,
            timestamp=datetime.now(),
            data={
                "interaction_type": interaction_type,
                "details": details
            },
            importance=0.7
        )
        
        self._save_activity(event)
    
    def _save_activity(self, event: ActivityEvent):
        """Guardar evento de actividad."""
        # Agregar al buffer
        self.activity_buffer.append(event)
        
        # Guardar en base de datos (en thread separado)
        threading.Thread(
            target=self._save_to_database,
            args=(event,),
            daemon=True
        ).start()
        
        # También guardar en archivo de log diario
        self._save_to_log_file(event)
    
    def _save_to_database(self, event: ActivityEvent):
        """Guardar evento en base de datos SQLite."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO activity_events 
                (id, activity_type, timestamp, data, duration, importance)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                event.id,
                event.activity_type.value,
                event.timestamp.isoformat(),
                json.dumps(event.data),
                event.duration,
                event.importance
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error saving activity to database: {e}")
    
    def _save_to_log_file(self, event: ActivityEvent):
        """Guardar evento en archivo de log diario."""
        try:
            date_str = datetime.now().strftime("%Y-%m-%d")
            log_file = os.path.join(self.log_dir, f"activity_{date_str}.log")
            
            with open(log_file, "a", encoding="utf-8") as f:
                log_entry = {
                    "timestamp": event.timestamp.isoformat(),
                    "type": event.activity_type.value,
                    "data": event.data,
                    "duration": event.duration
                }
                f.write(json.dumps(log_entry) + "\n")
                
        except Exception as e:
            logger.error(f"Error saving activity to log file: {e}")
    
    def _update_app_usage(self, app_name: str, duration: float):
        """Actualizar estadísticas de uso de aplicación."""
        if app_name not in self.application_usage:
            self.application_usage[app_name] = ApplicationUsage(name=app_name)
        
        usage = self.application_usage[app_name]
        usage.total_time += duration
        usage.sessions += 1
        usage.last_used = datetime.now()
        
        # Calcular frecuencia (simplificado)
        usage.frequency = usage.sessions / max(usage.total_time / 3600, 1)
        
        # Guardar en base de datos
        self._save_app_usage(usage)
    
    def _save_app_usage(self, usage: ApplicationUsage):
        """Guardar estadísticas de aplicación en base de datos."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO app_usage 
                (app_name, total_time, sessions, last_used, frequency)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                usage.name,
                usage.total_time,
                usage.sessions,
                usage.last_used.isoformat() if usage.last_used else None,
                usage.frequency
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error saving app usage: {e}")
    
    # ─── Métodos de Monitoreo Continuo ─────────────────────────────────────────
    
    def start_monitoring(self):
        """Iniciar monitoreo continuo de actividad."""
        if not self.enabled:
            logger.warning("Activity monitoring is disabled")
            return
        
        if self.is_monitoring:
            logger.warning("Activity monitoring already running")
            return
        
        self.is_monitoring = True
        self.monitor_thread = threading.Thread(
            target=self._monitoring_loop,
            daemon=True
        )
        self.monitor_thread.start()
        
        logger.info("Activity monitoring started")
    
    def stop_monitoring(self):
        """Detener monitoreo de actividad."""
        self.is_monitoring = False
        
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        
        logger.info("Activity monitoring stopped")
    
    def _monitoring_loop(self):
        """Loop principal de monitoreo."""
        last_window = None
        last_window_time = None
        
        while self.is_monitoring:
            try:
                # Capturar ventana activa
                window_info = self.get_active_window_info()
                current_time = time.time()
                
                if window_info:
                    # Detectar cambio de ventana
                    if self.detect_context_change(last_window, window_info):
                        if last_window and last_window_time:
                            # Calcular duración de la ventana anterior
                            duration = current_time - last_window_time
                            
                            # Registrar cambio de foco
                            self.log_window_focus(last_window, duration)
                        
                        # Actualizar para nueva ventana
                        last_window = window_info
                        last_window_time = current_time
                
                # Capturar actividad del sistema periódicamente
                if int(current_time) % 30 == 0:  # Cada 30 segundos
                    system_activity = self.get_system_activity()
                    self.log_system_event("system_metrics", system_activity)
                
                # Esperar hasta la próxima captura
                time.sleep(MONITOR_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(MONITOR_INTERVAL * 2)  # Esperar más en caso de error
    
    # ─── Métodos de Consulta y Análisis ────────────────────────────────────────
    
    def get_recent_activity(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Obtener actividad reciente."""
        recent = list(self.activity_buffer)[-limit:]
        return [event.to_dict() for event in recent]
    
    def get_activity_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Obtener resumen de actividad de las últimas horas."""
        try:
            import sqlite3
            from datetime import datetime, timedelta
            
            cutoff = datetime.now() - timedelta(hours=hours)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Contar eventos por tipo
            cursor.execute('''
                SELECT activity_type, COUNT(*) as count, 
                       SUM(duration) as total_duration
                FROM activity_events
                WHERE timestamp >= ?
                GROUP BY activity_type
            ''', (cutoff.isoformat(),))
            
            type_stats = {}
            for row in cursor.fetchall():
                type_stats[row[0]] = {
                    "count": row[1],
                    "total_duration": row[2] or 0
                }
            
            # Aplicaciones más usadas
            cursor.execute('''
                SELECT app_name, total_time, sessions
                FROM app_usage
                WHERE last_used >= ?
                ORDER BY total_time DESC
                LIMIT 5
            ''', (cutoff.isoformat(),))
            
            top_apps = []
            for row in cursor.fetchall():
                top_apps.append({
                    "name": row[0],
                    "total_time_hours": round(row[1] / 3600, 2),
                    "sessions": row[2]
                })
            
            # Patrones por hora
            cursor.execute('''
                SELECT strftime('%H', timestamp) as hour, 
                       activity_type, COUNT(*) as count
                FROM activity_events
                WHERE timestamp >= ?
                GROUP BY hour, activity_type
                ORDER BY hour
            ''', (cutoff.isoformat(),))
            
            hourly_patterns = defaultdict(dict)
            for row in cursor.fetchall():
                hourly_patterns[row[0]][row[1]] = row[2]
            
            conn.close()
            
            return {
                "time_period_hours": hours,
                "event_counts": type_stats,
                "top_applications": top_apps,
                "hourly_patterns": dict(hourly_patterns),
                "current_window": self.current_window,
                "monitoring_enabled": self.enabled,
                "is_monitoring": self.is_monitoring
            }
            
        except Exception as e:
            logger.error(f"Error getting activity summary: {e}")
            return {"error": str(e)}
    
    def get_user_patterns(self) -> Dict[str, Any]:
        """Obtener patrones de uso del usuario."""
        try:
            # Análisis simplificado de patrones
            patterns = {
                "favorite_apps": [],
                "work_hours": [],
                "frequent_actions": [],
                "context_switches_per_hour": 0
            }
            
            # Aplicaciones favoritas (más tiempo usado)
            if self.application_usage:
                favorite_apps = sorted(
                    self.application_usage.values(),
                    key=lambda x: x.total_time,
                    reverse=True
                )[:5]
                
                patterns["favorite_apps"] = [
                    {
                        "name": app.name,
                        "hours": round(app.total_time / 3600, 1),
                        "frequency": round(app.frequency, 2)
                    }
                    for app in favorite_apps
                ]
            
            # Análisis de actividad reciente para patrones
            recent_activity = self.get_recent_activity(limit=100)
            if recent_activity:
                # Contar cambios de contexto
                context_changes = sum(
                    1 for event in recent_activity 
                    if event.get("activity_type") == "window_focus"
                )
                
                hours_covered = min(len(recent_activity) * MONITOR_INTERVAL / 3600, 24)
                patterns["context_switches_per_hour"] = round(
                    context_changes / max(hours_covered, 1), 1
                )
            
            return patterns
            
        except Exception as e:
            logger.error(f"Error getting user patterns: {e}")
            return {"error": str(e)}
    
    def cleanup_old_data(self, days_to_keep: int = MAX_HISTORY_DAYS):
        """Limpiar datos antiguos."""
        try:
            import sqlite3
            from datetime import datetime, timedelta
            
            cutoff = datetime.now() - timedelta(days=days_to_keep)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Eliminar eventos antiguos
            cursor.execute(
                'DELETE FROM activity_events WHERE timestamp < ?',
                (cutoff.isoformat(),)
            )
            
            deleted_events = cursor.rowcount
            
            # Eliminar patrones diarios antiguos
            cursor.execute(
                'DELETE FROM daily_patterns WHERE date < ?',
                (cutoff.strftime("%Y-%m-%d"),)
            )
            
            deleted_patterns = cursor.rowcount
            
            conn.commit()
            conn.close()
            
            # Limpiar archivos de log antiguos
            self._cleanup_old_logs(days_to_keep)
            
            logger.info(f"Cleaned up {deleted_events} old events and {deleted_patterns} old patterns")
            
            return {
                "deleted_events": deleted_events,
                "deleted_patterns": deleted_patterns
            }
            
        except Exception as e:
            logger.error(f"Error cleaning up old data: {e}")
            return {"error": str(e)}
    
    def _cleanup_old_logs(self, days_to_keep: int):
        """Limpiar archivos de log antiguos."""
        try:
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)
            
            for filename in os.listdir(self.log_dir):
                if filename.startswith("activity_") and filename.endswith(".log"):
                    # Extraer fecha del nombre del archivo
                    date_str = filename.replace("activity_", "").replace(".log", "")
                    
                    try:
                        file_date = datetime.strptime(date_str, "%Y-%m-%d")
                        
                        if file_date < cutoff_date:
                            file_path = os.path.join(self.log_dir, filename)
                            os.remove(file_path)
                            logger.debug(f"Removed old log file: {filename}")
                    except ValueError:
                        continue
                        
        except Exception as e:
            logger.error(f"Error cleaning up old logs: {e}")
    
    # ─── Métodos de Control ────────────────────────────────────────────────────
    
    def enable(self):
        """Habilitar monitorización de actividad."""
        self.enabled = True
        logger.info("Activity monitoring enabled")
        
        # Iniciar monitoreo si no está corriendo
        if not self.is_monitoring:
            self.start_monitoring()
    
    def disable(self):
        """Deshabilitar monitorización de actividad."""
        self.enabled = False
        logger.info("Activity monitoring disabled")
        
        # Detener monitoreo
        self.stop_monitoring()
    
    def is_active(self) -> bool:
        """Verificar si el monitor está activo."""
        return self.enabled and self.is_monitoring
    
    def get_status(self) -> Dict[str, Any]:
        """Obtener estado del monitor."""
        return {
            "enabled": self.enabled,
            "is_monitoring": self.is_monitoring,
            "buffer_size": len(self.activity_buffer),
            "app_usage_count": len(self.application_usage),
            "monitor_interval": MONITOR_INTERVAL,
            "db_path": self.db_path,
            "log_dir": self.log_dir
        }


# ─── Singleton para acceso global ──────────────────────────────────────────────

_activity_monitor_instance = None

def get_activity_monitor(enabled: bool = False) -> ActivityMonitor:
    """Obtener instancia singleton del monitor de actividad."""
    global _activity_monitor_instance
    
    if _activity_monitor_instance is None:
        _activity_monitor_instance = ActivityMonitor(enabled=enabled)
    elif enabled != _activity_monitor_instance.enabled:
        # Actualizar estado si es diferente
        if enabled:
            _activity_monitor_instance.enable()
        else:
            _activity_monitor_instance.disable()
    
    return _activity_monitor_instance


# ─── Funciones de Utilidad ─────────────────────────────────────────────────────

def test_activity_monitor():
    """Probar el sistema de monitorización de actividad."""
    print("👀 Probando monitor de actividad...")
    
    monitor = get_activity_monitor(enabled=True)
    
    # Probar captura de ventana
    print("1. Capturando ventana activa...")
    window_info = monitor.get_active_window_info()
    if window_info:
        print(f"   Ventana: {window_info.get('title', 'Unknown')}")
        print(f"   Clase: {window_info.get('class', 'Unknown')}")
    else:
        print("   No se pudo capturar ventana")
    
    # Probar actividad del sistema
    print("\n2. Capturando actividad del sistema...")
    system_activity = monitor.get_system_activity()
    if "error" not in system_activity:
        print(f"   CPU: {system_activity.get('cpu_percent', 0)}%")
        print(f"   Memoria: {system_activity.get('memory_percent', 0)}%")
    else:
        print(f"   Error: {system_activity.get('error')}")
    
    # Probar registro de actividad
    print("\n3. Registrando eventos de prueba...")
    monitor.log_application_use("terminal", "command_executed", {"command": "ls -la"})
    monitor.log_user_interaction("keyboard", {"keys_pressed": 50})
    monitor.log_system_event("test_event", {"test": True})
    
    # Iniciar monitoreo breve
    print("\n4. Iniciando monitoreo breve...")
    monitor.start_monitoring()
    time.sleep(3)
    
    # Obtener resumen
    print("\n5. Obteniendo resumen...")
    summary = monitor.get_activity_summary(hours=1)
    print(f"   Eventos registrados: {len(summary.get('event_counts', {}))} tipos")
    
    # Detener monitoreo
    monitor.stop_monitoring()
    
    # Estado final
    status = monitor.get_status()
    print(f"\n6. Estado final: {'ACTIVO' if status['is_monitoring'] else 'INACTIVO'}")
    print(f"   Eventos en buffer: {status['buffer_size']}")
    
    print("\n✅ Monitor de actividad probado exitosamente!")


if __name__ == "__main__":
    # Para pruebas, ejecutar con logging básico
    logging.basicConfig(level=logging.INFO)
    test_activity_monitor()