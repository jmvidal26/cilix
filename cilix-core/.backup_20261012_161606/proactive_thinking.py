"""
proactive_thinking.py — Sistema de Pensamiento Proactivo para Sylix OS Core

Características:
1. Análisis predictivo basado en patrones
2. Sugerencias automáticas contextuales
3. Alertas proactivas
4. Automatización inteligente
5. Aprendizaje de hábitos del usuario
"""

import os
import json
import time
import threading
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
import logging
from collections import defaultdict, deque
import heapq

logger = logging.getLogger("sylix.proactive")

# Configuración
PROACTIVE_DB_PATH = os.path.expanduser("~/.config/sylix/proactive.db")
PROACTIVE_RULES_DIR = os.path.expanduser("~/.config/sylix/proactive_rules")
THINKING_INTERVAL = 30  # segundos entre ciclos de pensamiento
MAX_SUGGESTIONS = 5    # sugerencias máximas simultáneas

# Tipos de pensamiento proactivo
class ProactiveType(Enum):
    SUGGESTION = "suggestion"
    ALERT = "alert"
    AUTOMATION = "automation"
    REMINDER = "reminder"
    OPTIMIZATION = "optimization"
    LEARNING = "learning"

@dataclass
class ProactiveThought:
    """Pensamiento proactivo generado."""
    id: str
    thought_type: ProactiveType
    timestamp: datetime
    priority: float  # 0.0 - 1.0
    confidence: float  # 0.0 - 1.0
    content: Dict[str, Any]
    action_required: bool = False
    action_callback: Optional[str] = None
    expires: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "thought_type": self.thought_type.value,
            "timestamp": self.timestamp.isoformat(),
            "priority": self.priority,
            "confidence": self.confidence,
            "content": self.content,
            "action_required": self.action_required,
            "action_callback": self.action_callback,
            "expires": self.expires.isoformat() if self.expires else None
        }

@dataclass
class PatternRule:
    """Regla para detección de patrones."""
    id: str
    pattern_type: str
    conditions: List[Dict[str, Any]]
    actions: List[Dict[str, Any]]
    confidence: float = 0.5
    priority: float = 0.5
    enabled: bool = True
    last_triggered: Optional[datetime] = None
    trigger_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "pattern_type": self.pattern_type,
            "conditions": self.conditions,
            "actions": self.actions,
            "confidence": self.confidence,
            "priority": self.priority,
            "enabled": self.enabled,
            "last_triggered": self.last_triggered.isoformat() if self.last_triggered else None,
            "trigger_count": self.trigger_count
        }

class ProactiveThinker:
    """Sistema principal de pensamiento proactivo."""
    
    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self.is_thinking = False
        self.thinking_thread = None
        
        # Almacenamiento
        self.active_thoughts = []  # Cola de prioridad
        self.thought_history = deque(maxlen=1000)
        self.pattern_rules = {}
        self.user_habits = defaultdict(list)
        
        # Contexto actual
        self.current_context = {}
        self.last_analysis_time = None
        
        # Configuración
        self.db_path = PROACTIVE_DB_PATH
        self.rules_dir = PROACTIVE_RULES_DIR
        
        # Crear directorios
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        os.makedirs(self.rules_dir, exist_ok=True)
        
        # Inicializar base de datos
        self._init_database()
        
        # Cargar reglas y hábitos
        self._load_pattern_rules()
        self._load_default_rules()
        
        logger.info(f"Proactive Thinker inicializado (enabled={self.enabled})")
    
    def _init_database(self):
        """Inicializar base de datos para pensamiento proactivo."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Tabla de pensamientos
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS proactive_thoughts (
                    id TEXT PRIMARY KEY,
                    thought_type TEXT,
                    timestamp TEXT,
                    priority REAL,
                    confidence REAL,
                    content TEXT,
                    action_required INTEGER,
                    action_callback TEXT,
                    expires TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Tabla de reglas
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS pattern_rules (
                    id TEXT PRIMARY KEY,
                    pattern_type TEXT,
                    conditions TEXT,
                    actions TEXT,
                    confidence REAL,
                    priority REAL,
                    enabled INTEGER,
                    last_triggered TEXT,
                    trigger_count INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Tabla de hábitos
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_habits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    habit_type TEXT,
                    pattern TEXT,
                    frequency REAL,
                    last_observed TEXT,
                    confidence REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Índices
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_thoughts_priority ON proactive_thoughts(priority DESC)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_thoughts_type ON proactive_thoughts(thought_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_rules_enabled ON pattern_rules(enabled)')
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error initializing proactive database: {e}")
    
    def _load_default_rules(self):
        """Cargar reglas proactivas por defecto."""
        default_rules = [
            # Regla 1: Sugerir descanso después de mucho tiempo en una aplicación
            {
                "id": "suggest_break",
                "pattern_type": "extended_use",
                "conditions": [
                    {"type": "app_usage", "app": "any", "duration_minutes": 45}
                ],
                "actions": [
                    {"type": "suggestion", "message": "Llevas mucho tiempo trabajando. ¿Quieres tomar un descanso?", "priority": 0.7}
                ],
                "confidence": 0.8,
                "priority": 0.7,
                "enabled": True
            },
            
            # Regla 2: Sugerir organizar archivos en descargas llenas
            {
                "id": "organize_downloads",
                "pattern_type": "cluttered_folder",
                "conditions": [
                    {"type": "folder_size", "path": "~/Downloads", "threshold_mb": 500}
                ],
                "actions": [
                    {"type": "suggestion", "message": "Tu carpeta de descargas está bastante llena. ¿Quieres que la organice?", "priority": 0.6}
                ],
                "confidence": 0.7,
                "priority": 0.6,
                "enabled": True
            },
            
            # Regla 3: Recordar reuniones basadas en calendario
            {
                "id": "meeting_reminder",
                "pattern_type": "calendar_event",
                "conditions": [
                    {"type": "time_of_day", "hour": "any"},
                    {"type": "has_calendar_events", "minutes_ahead": 15}
                ],
                "actions": [
                    {"type": "reminder", "message": "Tienes una reunión pronto. ¿Quieres que te prepare algo?", "priority": 0.9}
                ],
                "confidence": 0.9,
                "priority": 0.8,
                "enabled": True
            },
            
            # Regla 4: Optimización de sistema cuando hay alto uso de RAM
            {
                "id": "system_optimization",
                "pattern_type": "high_resource_usage",
                "conditions": [
                    {"type": "system_metric", "metric": "memory_percent", "threshold": 85}
                ],
                "actions": [
                    {"type": "suggestion", "message": "El sistema está usando mucha memoria. ¿Quieres que optimice algunos procesos?", "priority": 0.8}
                ],
                "confidence": 0.75,
                "priority": 0.7,
                "enabled": True
            },
            
            # Regla 5: Sugerir aprendizaje basado en patrones de uso
            {
                "id": "learning_suggestion",
                "pattern_type": "repetitive_task",
                "conditions": [
                    {"type": "repeated_action", "action_pattern": "same", "count": 3, "timeframe_hours": 24}
                ],
                "actions": [
                    {"type": "suggestion", "message": "Veo que repites esta tarea. ¿Quieres que aprenda a automatizarla?", "priority": 0.6}
                ],
                "confidence": 0.65,
                "priority": 0.6,
                "enabled": True
            }
        ]
        
        for rule_data in default_rules:
            rule = PatternRule(
                id=rule_data["id"],
                pattern_type=rule_data["pattern_type"],
                conditions=rule_data["conditions"],
                actions=rule_data["actions"],
                confidence=rule_data["confidence"],
                priority=rule_data["priority"],
                enabled=rule_data["enabled"]
            )
            self.pattern_rules[rule.id] = rule
            self._save_rule_to_database(rule)
    
    def _load_pattern_rules(self):
        """Cargar reglas desde la base de datos."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM pattern_rules WHERE enabled = 1')
            
            for row in cursor.fetchall():
                try:
                    rule = PatternRule(
                        id=row[0],
                        pattern_type=row[1],
                        conditions=json.loads(row[2]),
                        actions=json.loads(row[3]),
                        confidence=row[4],
                        priority=row[5],
                        enabled=bool(row[6]),
                        last_triggered=datetime.fromisoformat(row[7]) if row[7] else None,
                        trigger_count=row[8]
                    )
                    self.pattern_rules[rule.id] = rule
                except Exception as e:
                    logger.error(f"Error parsing rule {row[0]}: {e}")
            
            conn.close()
            logger.debug(f"Loaded {len(self.pattern_rules)} pattern rules")
            
        except Exception as e:
            logger.error(f"Error loading pattern rules: {e}")
    
    def _save_rule_to_database(self, rule: PatternRule):
        """Guardar regla en la base de datos."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO pattern_rules 
                (id, pattern_type, conditions, actions, confidence, priority, enabled, last_triggered, trigger_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                rule.id,
                rule.pattern_type,
                json.dumps(rule.conditions),
                json.dumps(rule.actions),
                rule.confidence,
                rule.priority,
                1 if rule.enabled else 0,
                rule.last_triggered.isoformat() if rule.last_triggered else None,
                rule.trigger_count
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error saving rule to database: {e}")
    
    # ─── Métodos de Análisis de Contexto ───────────────────────────────────────
    
    def update_context(self, context_data: Dict[str, Any]):
        """Actualizar contexto actual para análisis."""
        self.current_context.update(context_data)
        self.current_context["timestamp"] = datetime.now().isoformat()
        
        # Ejecutar análisis si está habilitado
        if self.enabled and self.is_thinking:
            self._analyze_context()
    
    def _analyze_context(self):
        """Analizar contexto actual y generar pensamientos."""
        if not self.current_context:
            return
        
        # Ejecutar reglas de patrón
        triggered_rules = self._evaluate_rules()
        
        # Generar pensamientos basados en reglas activadas
        for rule in triggered_rules:
            self._generate_thoughts_from_rule(rule)
        
        # Análisis de hábitos
        self._analyze_habits()
        
        # Optimización de pensamientos activos
        self._optimize_active_thoughts()
        
        self.last_analysis_time = datetime.now()
    
    def _evaluate_rules(self) -> List[PatternRule]:
        """Evaluar reglas contra el contexto actual."""
        triggered = []
        
        for rule in self.pattern_rules.values():
            if not rule.enabled:
                continue
            
            # Verificar si la regla debe dispararse
            if self._check_rule_conditions(rule):
                triggered.append(rule)
                
                # Actualizar estadísticas de la regla
                rule.last_triggered = datetime.now()
                rule.trigger_count += 1
                self._save_rule_to_database(rule)
                
                logger.debug(f"Rule triggered: {rule.id}")
        
        return triggered
    
    def _check_rule_conditions(self, rule: PatternRule) -> bool:
        """Verificar condiciones de una regla."""
        # Implementación simplificada - en producción sería más compleja
        for condition in rule.conditions:
            cond_type = condition.get("type", "")
            
            if cond_type == "app_usage":
                # Verificar uso de aplicación
                app = condition.get("app", "any")
                duration = condition.get("duration_minutes", 0)
                
                # Lógica simplificada
                if "current_app" in self.current_context:
                    current_app = self.current_context.get("current_app", {})
                    app_name = current_app.get("name", "")
                    app_duration = current_app.get("duration_minutes", 0)
                    
                    if (app == "any" or app == app_name) and app_duration >= duration:
                        return True
            
            elif cond_type == "folder_size":
                # Verificar tamaño de carpeta
                path = condition.get("path", "")
                threshold = condition.get("threshold_mb", 0)
                
                # Lógica simplificada
                if "folder_sizes" in self.current_context:
                    folder_size = self.current_context["folder_sizes"].get(path, 0)
                    if folder_size >= threshold:
                        return True
            
            elif cond_type == "system_metric":
                # Verificar métrica del sistema
                metric = condition.get("metric", "")
                threshold = condition.get("threshold", 0)
                
                if metric in self.current_context:
                    value = self.current_context.get(metric, 0)
                    if value >= threshold:
                        return True
        
        return False
    
    # ─── Métodos de Generación de Pensamientos ─────────────────────────────────
    
    def _generate_thoughts_from_rule(self, rule: PatternRule):
        """Generar pensamientos basados en una regla activada."""
        for action in rule.actions:
            action_type = action.get("type", "")
            
            if action_type == "suggestion":
                self._generate_suggestion(action, rule)
            elif action_type == "reminder":
                self._generate_reminder(action, rule)
            elif action_type == "alert":
                self._generate_alert(action, rule)
            elif action_type == "automation":
                self._generate_automation(action, rule)
    
    def _generate_suggestion(self, action: Dict[str, Any], rule: PatternRule):
        """Generar sugerencia proactiva."""
        thought_id = f"suggestion_{int(time.time())}_{rule.id}"
        
        thought = ProactiveThought(
            id=thought_id,
            thought_type=ProactiveType.SUGGESTION,
            timestamp=datetime.now(),
            priority=action.get("priority", rule.priority),
            confidence=rule.confidence,
            content={
                "message": action.get("message", "Tengo una sugerencia para ti."),
                "rule_id": rule.id,
                "context": self.current_context.copy()
            },
            action_required=True,
            action_callback="handle_suggestion",
            expires=datetime.now() + timedelta(minutes=30)  # Expira en 30 minutos
        )
        
        self._add_thought(thought)
    
    def _generate_reminder(self, action: Dict[str, Any], rule: PatternRule):
        """Generar recordatorio proactivo."""
        thought_id = f"reminder_{int(time.time())}_{rule.id}"
        
        thought = ProactiveThought(
            id=thought_id,
            thought_type=ProactiveType.REMINDER,
            timestamp=datetime.now(),
            priority=action.get("priority", rule.priority),
            confidence=rule.confidence,
            content={
                "message": action.get("message", "Recordatorio importante."),
                "rule_id": rule.id,
                "context": self.current_context.copy()
            },
            action_required=False,
            expires=datetime.now() + timedelta(hours=1)  # Expira en 1 hora
        )
        
        self._add_thought(thought)
    
    def _generate_alert(self, action: Dict[str, Any], rule: PatternRule):
        """Generar alerta proactiva."""
        thought_id = f"alert_{int(time.time())}_{rule.id}"
        
        thought = ProactiveThought(
            id=thought_id,
            thought_type=ProactiveType.ALERT,
            timestamp=datetime.now(),
            priority=action.get("priority", 0.9),  # Alertas tienen alta prioridad
            confidence=rule.confidence,
            content={
                "message": action.get("message", "¡Alerta importante!"),
                "rule_id": rule.id,
                "context": self.current_context.copy(),
                "urgency": action.get("urgency", "medium")
            },
            action_required=True,
            action_callback="handle_alert",
            expires=datetime.now() + timedelta(minutes=15)  # Expira en 15 minutos
        )
        
        self._add_thought(thought)
    
    def _generate_automation(self, action: Dict[str, Any], rule: PatternRule):
        """Generar pensamiento de automatización."""
        thought_id = f"automation_{int(time.time())}_{rule.id}"
        
        thought = ProactiveThought(
            id=thought_id,
            thought_type=ProactiveType.AUTOMATION,
            timestamp=datetime.now(),
            priority=action.get("priority", rule.priority),
            confidence=rule.confidence,
            content={
                "message": action.get("message", "Puedo automatizar esto para ti."),
                "rule_id": rule.id,
                "context": self.current_context.copy(),
                "automation_steps": action.get("steps", [])
            },
            action_required=True,
            action_callback="handle_automation",
            expires=datetime.now() + timedelta(minutes=45)
        )
        
        self._add_thought(thought)
    
    def _add_thought(self, thought: ProactiveThought):
        """Agregar pensamiento a la cola activa."""
        # Usar priority como primer criterio, luego confidence
        heap_priority = (-thought.priority, -thought.confidence, thought.timestamp.timestamp())
        
        heapq.heappush(self.active_thoughts, (heap_priority, thought))
        self.thought_history.append(thought)
        
        # Guardar en base de datos
        self._save_thought_to_database(thought)
        
        # Limitar número de pensamientos activos
        if len(self.active_thoughts) > MAX_SUGGESTIONS:
            heapq.heappop(self.active_thoughts)
        
        logger.debug(f"Added proactive thought: {thought.thought_type.value} (priority: {thought.priority})")
    
    def _save_thought_to_database(self, thought: ProactiveThought):
        """Guardar pensamiento en la base de datos."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO proactive_thoughts 
                (id, thought_type, timestamp, priority, confidence, content, action_required, action_callback, expires)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                thought.id,
                thought.thought_type.value,
                thought.timestamp.isoformat(),
                thought.priority,
                thought.confidence,
                json.dumps(thought.content),
                1 if thought.action_required else 0,
                thought.action_callback,
                thought.expires.isoformat() if thought.expires else None
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error saving thought to database: {e}")
    
    # ─── Métodos de Análisis de Hábitos ────────────────────────────────────────
    
    def _analyze_habits(self):
        """Analizar y aprender hábitos del usuario."""
        # Implementación simplificada
        if "user_actions" in self.current_context:
            actions = self.current_context["user_actions"]
            
            for action in actions[:10]:  # Analizar últimas 10 acciones
                action_type = action.get("type", "")
                action_data = action.get("data", {})
                
                # Agregar a hábitos
                habit_key = f"{action_type}_{hash(str(action_data)) % 1000}"
                self.user_habits[habit_key].append(datetime.now())
                
                # Aprender frecuencia
                self._learn_habit_frequency(habit_key)
    
    def _learn_habit_frequency(self, habit_key: str):
        """Aprender frecuencia de un hábito."""
        occurrences = self.user_habits[habit_key]
        
        if len(occurrences) >= 3:
            # Calcular tiempo promedio entre ocurrencias
            times = sorted(occurrences)
            intervals = []
            
            for i in range(1, len(times)):
                interval = (times[i] - times[i-1]).total_seconds()
                intervals.append(interval)
            
            if intervals:
                avg_interval = sum(intervals) / len(intervals)
                
                # Si el hábito ocurre regularmente, considerar para proactividad
                if avg_interval < 3600:  # Menos de 1 hora entre ocurrencias
                    self._generate_habit_based_thought(habit_key, avg_interval)
    
    def _generate_habit_based_thought(self, habit_key: str, frequency: float):
        """Generar pensamiento basado en hábito aprendido."""
        # Por ahora, implementación simplificada
        thought_id = f"habit_{int(time.time())}_{habit_key}"
        
        thought = ProactiveThought(
            id=thought_id,
            thought_type=ProactiveType.LEARNING,
            timestamp=datetime.now(),
            priority=0.6,
            confidence=0.7,
            content={
                "message": "He notado un patrón en tus acciones. ¿Quieres que te ayude con esto?",
                "habit_key": habit_key,
                "frequency_seconds": frequency
            },
            action_required=False,
            expires=datetime.now() + timedelta(hours=2)
        )
        
        self._add_thought(thought)
    
    # ─── Métodos de Optimización ───────────────────────────────────────────────
    
    def _optimize_active_thoughts(self):
        """Optimizar pensamientos activos (limpiar expirados, etc.)."""
        current_time = datetime.now()
        
        # Filtrar pensamientos expirados
        new_active = []
        for priority, thought in self.active_thoughts:
            if thought.expires and thought.expires < current_time:
                logger.debug(f"Thought expired: {thought.id}")
                continue
            
            # Verificar si el pensamiento sigue siendo relevante
            if self._is_thought_still_relevant(thought):
                new_active.append((priority, thought))
            else:
                logger.debug(f"Thought no longer relevant: {thought.id}")
        
        # Reconstruir heap
        self.active_thoughts = []
        for item in new_active:
            heapq.heappush(self.active_thoughts, item)
    
    def _is_thought_still_relevant(self, thought: ProactiveThought) -> bool:
        """Verificar si un pensamiento sigue siendo relevante."""
        # Verificar contexto
        thought_context = thought.content.get("context", {})
        
        # Comparación simplificada
        for key, value in thought_context.items():
            if key in self.current_context:
                current_value = self.current_context[key]
                
                # Si el contexto ha cambiado significativamente
                if isinstance(value, (int, float)) and isinstance(current_value, (int, float)):
                    if abs(value - current_value) > (value * 0.3):  # 30% de cambio
                        return False
        
        return True
    
    # ─── Métodos de Consulta y Gestión ─────────────────────────────────────────
    
    def get_top_thoughts(self, limit: int = 3) -> List[Dict[str, Any]]:
        """Obtener pensamientos más importantes."""
        thoughts = []
        
        # Obtener de mayor prioridad
        temp_heap = self.active_thoughts.copy()
        for _ in range(min(limit, len(temp_heap))):
            if temp_heap:
                priority, thought = heapq.heappop(temp_heap)
                thoughts.append(thought.to_dict())
        
        return thoughts
    
    def get_thought_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Obtener historial de pensamientos."""
        recent = list(self.thought_history)[-limit:]
        return [thought.to_dict() for thought in recent]
    
    def acknowledge_thought(self, thought_id: str, user_response: Optional[str] = None):
        """Reconocer/un pensamiento (usuario lo vio/respondió)."""
        # Buscar y remover de pensamientos activos
        new_active = []
        acknowledged = None
        
        for priority, thought in self.active_thoughts:
            if thought.id == thought_id:
                acknowledged = thought
                # No agregar de nuevo a activos
                continue
            new_active.append((priority, thought))
        
        # Reconstruir heap
        self.active_thoughts = []
        for item in new_active:
            heapq.heappush(self.active_thoughts, item)
        
        if acknowledged:
            # Guardar respuesta del usuario
            self._save_user_response(thought_id, user_response)
            
            # Aprender de la respuesta
            if user_response and "sí" in user_response.lower():
                # Usuario aceptó sugerencia - aumentar confianza de regla relacionada
                rule_id = acknowledged.content.get("rule_id")
                if rule_id and rule_id in self.pattern_rules:
                    rule = self.pattern_rules[rule_id]
                    rule.confidence = min(1.0, rule.confidence + 0.1)
                    self._save_rule_to_database(rule)
            
            logger.info(f"Thought acknowledged: {thought_id}")
            return True
        
        return False
    
    def _save_user_response(self, thought_id: str, response: Optional[str]):
        """Guardar respuesta del usuario."""
        # Por ahora, solo log
        if response:
            logger.debug(f"User response to {thought_id}: {response}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Obtener estadísticas del pensador proactivo."""
        return {
            "enabled": self.enabled,
            "is_thinking": self.is_thinking,
            "active_thoughts": len(self.active_thoughts),
            "thought_history": len(self.thought_history),
            "pattern_rules": len(self.pattern_rules),
            "user_habits": len(self.user_habits),
            "last_analysis": self.last_analysis_time.isoformat() if self.last_analysis_time else None,
            "thinking_interval": THINKING_INTERVAL
        }
    
    # ─── Métodos de Control ────────────────────────────────────────────────────
    
    def start_thinking(self):
        """Iniciar ciclo de pensamiento proactivo."""
        if not self.enabled:
            logger.warning("Proactive thinking is disabled")
            return
        
        if self.is_thinking:
            logger.warning("Proactive thinking already running")
            return
        
        self.is_thinking = True
        self.thinking_thread = threading.Thread(
            target=self._thinking_loop,
            daemon=True
        )
        self.thinking_thread.start()
        
        logger.info("Proactive thinking started")
    
    def stop_thinking(self):
        """Detener pensamiento proactivo."""
        self.is_thinking = False
        
        if self.thinking_thread:
            self.thinking_thread.join(timeout=5)
        
        logger.info("Proactive thinking stopped")
    
    def _thinking_loop(self):
        """Loop principal de pensamiento proactivo."""
        while self.is_thinking:
            try:
                # Ejecutar análisis si hay contexto
                if self.current_context:
                    self._analyze_context()
                
                # Limpiar pensamientos expirados
                self._optimize_active_thoughts()
                
                # Esperar hasta el próximo ciclo
                time.sleep(THINKING_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in thinking loop: {e}")
                time.sleep(THINKING_INTERVAL * 2)
    
    def enable(self):
        """Habilitar pensamiento proactivo."""
        self.enabled = True
        logger.info("Proactive thinking enabled")
        
        # Iniciar pensamiento si no está corriendo
        if not self.is_thinking:
            self.start_thinking()
    
    def disable(self):
        """Deshabilitar pensamiento proactivo."""
        self.enabled = False
        logger.info("Proactive thinking disabled")
        
        # Detener pensamiento
        self.stop_thinking()
    
    def add_custom_rule(self, rule_data: Dict[str, Any]) -> bool:
        """Agregar regla personalizada."""
        try:
            rule = PatternRule(
                id=rule_data.get("id", f"custom_{int(time.time())}"),
                pattern_type=rule_data.get("pattern_type", "custom"),
                conditions=rule_data.get("conditions", []),
                actions=rule_data.get("actions", []),
                confidence=rule_data.get("confidence", 0.5),
                priority=rule_data.get("priority", 0.5),
                enabled=rule_data.get("enabled", True)
            )
            
            self.pattern_rules[rule.id] = rule
            self._save_rule_to_database(rule)
            
            logger.info(f"Custom rule added: {rule.id}")
            return True
            
        except Exception as e:
            logger.error(f"Error adding custom rule: {e}")
            return False
    
    def cleanup_old_data(self, days_to_keep: int = 7):
        """Limpiar datos antiguos."""
        try:
            import sqlite3
            from datetime import datetime, timedelta
            
            cutoff = datetime.now() - timedelta(days=days_to_keep)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Eliminar pensamientos antiguos
            cursor.execute(
                'DELETE FROM proactive_thoughts WHERE timestamp < ?',
                (cutoff.isoformat(),)
            )
            
            deleted_thoughts = cursor.rowcount
            
            # Eliminar hábitos antiguos
            cursor.execute(
                'DELETE FROM user_habits WHERE last_observed < ?',
                (cutoff.isoformat(),)
            )
            
            deleted_habits = cursor.rowcount
            
            conn.commit()
            conn.close()
            
            logger.info(f"Cleaned up {deleted_thoughts} old thoughts and {deleted_habits} old habits")
            
            return {
                "deleted_thoughts": deleted_thoughts,
                "deleted_habits": deleted_habits
            }
            
        except Exception as e:
            logger.error(f"Error cleaning up old data: {e}")
            return {"error": str(e)}


# ─── Singleton para acceso global ──────────────────────────────────────────────

_proactive_thinker_instance = None

def get_proactive_thinker(enabled: bool = False) -> ProactiveThinker:
    """Obtener instancia singleton del pensador proactivo."""
    global _proactive_thinker_instance
    
    if _proactive_thinker_instance is None:
        _proactive_thinker_instance = ProactiveThinker(enabled=enabled)
    elif enabled != _proactive_thinker_instance.enabled:
        # Actualizar estado si es diferente
        if enabled:
            _proactive_thinker_instance.enable()
        else:
            _proactive_thinker_instance.disable()
    
    return _proactive_thinker_instance


# ─── Funciones de Utilidad ─────────────────────────────────────────────────────

def test_proactive_thinking():
    """Probar el sistema de pensamiento proactivo."""
    print("🤔 Probando pensamiento proactivo...")
    
    thinker = get_proactive_thinker(enabled=True)
    
    # Probar contexto
    print("1. Actualizando contexto...")
    thinker.update_context({
        "current_app": {"name": "terminal", "duration_minutes": 50},
        "memory_percent": 90,
        "user_actions": [
            {"type": "command", "data": {"command": "ls -la"}},
            {"type": "command", "data": {"command": "cd ~"}}
        ]
    })
    
    # Iniciar pensamiento
    print("2. Iniciando pensamiento...")
    thinker.start_thinking()
    time.sleep(5)
    
    # Obtener pensamientos
    print("3. Obteniendo pensamientos proactivos...")
    top_thoughts = thinker.get_top_thoughts(limit=3)
    
    if top_thoughts:
        print(f"   Pensamientos generados: {len(top_thoughts)}")
        for i, thought in enumerate(top_thoughts, 1):
            print(f"   {i}. {thought['thought_type']}: {thought['content']['message'][:50]}...")
    else:
        print("   No se generaron pensamientos")
    
    # Estadísticas
    print("\n4. Obteniendo estadísticas...")
    stats = thinker.get_statistics()
    print(f"   Pensamientos activos: {stats['active_thoughts']}")
    print(f"   Reglas cargadas: {stats['pattern_rules']}")
    
    # Detener pensamiento
    thinker.stop_thinking()
    
    # Estado final
    print(f"\n5. Estado final: {'ACTIVO' if stats['is_thinking'] else 'INACTIVO'}")
    
    print("\n✅ Pensamiento proactivo probado exitosamente!")


if __name__ == "__main__":
    # Para pruebas, ejecutar con logging básico
    logging.basicConfig(level=logging.INFO)
    test_proactive_thinking()