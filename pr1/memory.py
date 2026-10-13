"""
memory.py — Sistema de Memoria Persistente para Sylix OS Core

Características:
1. Memoria de conversación (historial persistente)
2. Memoria de contexto (preferencias, patrones)
3. Memoria de acciones (comandos ejecutados)
4. Memoria de sistema (estado, configuraciones)
5. Memoria episódica (eventos importantes)
"""

import os
import json
import time
import sqlite3
import hashlib
import pickle
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
import numpy as np
from collections import defaultdict, deque
import logging

logger = logging.getLogger("sylix.memory")

# Configuración
MEMORY_DB_PATH = os.path.expanduser("~/.config/sylix/memory.db")
MEMORY_DIR = os.path.expanduser("~/.config/sylix/memories")
CONTEXT_HISTORY_SIZE = 100  # Número de mensajes en contexto
ACTION_HISTORY_SIZE = 500   # Número de acciones recordadas

# Tipos de memoria
class MemoryType(Enum):
    CONVERSATION = "conversation"
    CONTEXT = "context"
    ACTION = "action"
    SYSTEM = "system"
    EPISODIC = "episodic"
    PREFERENCE = "preference"
    PATTERN = "pattern"

@dataclass
class MemoryEntry:
    """Entrada individual en la memoria."""
    id: str
    memory_type: MemoryType
    content: Dict[str, Any]
    timestamp: datetime
    importance: float = 0.5  # 0.0 - 1.0
    tags: List[str] = field(default_factory=list)
    expires: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "memory_type": self.memory_type.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "importance": self.importance,
            "tags": self.tags,
            "expires": self.expires.isoformat() if self.expires else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryEntry":
        return cls(
            id=data["id"],
            memory_type=MemoryType(data["memory_type"]),
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            importance=data.get("importance", 0.5),
            tags=data.get("tags", []),
            expires=datetime.fromisoformat(data["expires"]) if data.get("expires") else None
        )

@dataclass
class UserProfile:
    """Perfil persistente del usuario."""
    user_id: str
    preferences: Dict[str, Any] = field(default_factory=dict)
    interaction_patterns: Dict[str, List[str]] = field(default_factory=dict)
    frequent_commands: Dict[str, int] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)
    trust_level: float = 0.5  # 0.0 - 1.0
    
    def update_last_seen(self):
        self.last_seen = datetime.now()
    
    def add_preference(self, key: str, value: Any):
        self.preferences[key] = value
    
    def add_interaction(self, pattern: str, response: str):
        if pattern not in self.interaction_patterns:
            self.interaction_patterns[pattern] = []
        self.interaction_patterns[pattern].append(response)
    
    def add_command(self, command: str):
        self.frequent_commands[command] = self.frequent_commands.get(command, 0) + 1
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "preferences": self.preferences,
            "interaction_patterns": self.interaction_patterns,
            "frequent_commands": self.frequent_commands,
            "created_at": self.created_at.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "trust_level": self.trust_level
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserProfile":
        return cls(
            user_id=data["user_id"],
            preferences=data.get("preferences", {}),
            interaction_patterns=data.get("interaction_patterns", {}),
            frequent_commands=data.get("frequent_commands", {}),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_seen=datetime.fromisoformat(data["last_seen"]),
            trust_level=data.get("trust_level", 0.5)
        )

class PersistentMemory:
    """Sistema principal de memoria persistente."""
    
    def __init__(self, user_id: str = "default"):
        self.user_id = user_id
        self.db_path = MEMORY_DB_PATH
        self.memory_dir = MEMORY_DIR
        self.user_profile = None
        self.conversation_buffer = deque(maxlen=CONTEXT_HISTORY_SIZE)
        self.action_history = deque(maxlen=ACTION_HISTORY_SIZE)
        
        # Crear directorios si no existen
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        os.makedirs(self.memory_dir, exist_ok=True)
        
        # Inicializar base de datos
        self._init_database()
        
        # Cargar perfil del usuario
        self._load_user_profile()
    
    def _init_database(self):
        """Inicializar base de datos SQLite."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Tabla de memorias
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                memory_type TEXT,
                content TEXT,
                timestamp TEXT,
                importance REAL,
                tags TEXT,
                expires TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabla de perfiles de usuario
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                preferences TEXT,
                interaction_patterns TEXT,
                frequent_commands TEXT,
                created_at TEXT,
                last_seen TEXT,
                trust_level REAL
            )
        ''')
        
        # Tabla de estadísticas
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                metric TEXT,
                value REAL,
                timestamp TEXT
            )
        ''')
        
        # Índices para búsqueda eficiente
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_memories_user_type ON memories(user_id, memory_type)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_memories_timestamp ON memories(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories(tags)')
        
        conn.commit()
        conn.close()
    
    def _load_user_profile(self):
        """Cargar perfil del usuario desde la base de datos."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute(
                'SELECT * FROM user_profiles WHERE user_id = ?',
                (self.user_id,)
            )
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                self.user_profile = UserProfile.from_dict({
                    "user_id": row[0],
                    "preferences": json.loads(row[1]) if row[1] else {},
                    "interaction_patterns": json.loads(row[2]) if row[2] else {},
                    "frequent_commands": json.loads(row[3]) if row[3] else {},
                    "created_at": row[4],
                    "last_seen": row[5],
                    "trust_level": row[6]
                })
            else:
                # Crear nuevo perfil
                self.user_profile = UserProfile(user_id=self.user_id)
                self._save_user_profile()
                
        except Exception as e:
            logger.error(f"Error loading user profile: {e}")
            self.user_profile = UserProfile(user_id=self.user_id)
    
    def _save_user_profile(self):
        """Guardar perfil del usuario en la base de datos."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            profile_dict = self.user_profile.to_dict()
            
            cursor.execute('''
                INSERT OR REPLACE INTO user_profiles 
                (user_id, preferences, interaction_patterns, frequent_commands, created_at, last_seen, trust_level)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                profile_dict["user_id"],
                json.dumps(profile_dict["preferences"]),
                json.dumps(profile_dict["interaction_patterns"]),
                json.dumps(profile_dict["frequent_commands"]),
                profile_dict["created_at"],
                profile_dict["last_seen"],
                profile_dict["trust_level"]
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error saving user profile: {e}")
    
    # ─── Métodos de Memoria de Conversación ─────────────────────────────────────
    
    def add_conversation(self, role: str, content: str, metadata: Optional[Dict] = None):
        """Agregar mensaje a la memoria de conversación."""
        memory_id = hashlib.md5(f"{role}_{content}_{time.time()}".encode()).hexdigest()[:16]
        
        entry = MemoryEntry(
            id=memory_id,
            memory_type=MemoryType.CONVERSATION,
            content={
                "role": role,
                "content": content,
                "metadata": metadata or {}
            },
            timestamp=datetime.now(),
            importance=0.3,  # Conversaciones normales tienen importancia media
            tags=["conversation", role]
        )
        
        # Agregar al buffer en memoria
        self.conversation_buffer.append(entry)
        
        # Guardar en base de datos (solo mensajes importantes)
        if entry.importance > 0.5:
            self._save_memory(entry)
        
        logger.debug(f"Added conversation: {role}: {content[:50]}...")
    
    def get_recent_conversations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Obtener conversaciones recientes."""
        recent = list(self.conversation_buffer)[-limit:]
        return [{
            "role": entry.content["role"],
            "content": entry.content["content"],
            "timestamp": entry.timestamp.isoformat()
        } for entry in recent]
    
    def get_conversation_context(self, window_minutes: int = 60) -> str:
        """Obtener contexto de conversación para el modelo."""
        now = datetime.now()
        window_start = now - timedelta(minutes=window_minutes)
        
        context_lines = []
        for entry in self.conversation_buffer:
            if entry.timestamp >= window_start:
                role = entry.content["role"]
                content = entry.content["content"]
                time_str = entry.timestamp.strftime("%H:%M")
                context_lines.append(f"[{time_str}] {role}: {content}")
        
        return "\n".join(context_lines[-20:])  # Últimas 20 líneas
    
    # ─── Métodos de Memoria de Acciones ─────────────────────────────────────────
    
    def add_action(self, action_type: str, command: str, result: Dict[str, Any], 
                   success: bool = True, importance: float = 0.5):
        """Registrar una acción ejecutada."""
        memory_id = hashlib.md5(f"{action_type}_{command}_{time.time()}".encode()).hexdigest()[:16]
        
        entry = MemoryEntry(
            id=memory_id,
            memory_type=MemoryType.ACTION,
            content={
                "action_type": action_type,
                "command": command,
                "result": result,
                "success": success
            },
            timestamp=datetime.now(),
            importance=importance,
            tags=["action", action_type, "success" if success else "failure"]
        )
        
        # Agregar al historial en memoria
        self.action_history.append(entry)
        
        # Actualizar comandos frecuentes en el perfil
        self.user_profile.add_command(f"{action_type}:{command}")
        
        # Guardar en base de datos
        self._save_memory(entry)
        
        logger.debug(f"Added action: {action_type}: {command[:50]}...")
    
    def get_action_history(self, action_type: Optional[str] = None, 
                          limit: int = 20) -> List[Dict[str, Any]]:
        """Obtener historial de acciones."""
        actions = list(self.action_history)
        
        if action_type:
            actions = [a for a in actions if a.content["action_type"] == action_type]
        
        return [{
            "action_type": entry.content["action_type"],
            "command": entry.content["command"],
            "success": entry.content["success"],
            "timestamp": entry.timestamp.isoformat(),
            "result_summary": str(entry.content["result"])[:100]
        } for entry in actions[-limit:]]
    
    def get_success_rate(self, action_type: str = None) -> float:
        """Calcular tasa de éxito de acciones."""
        actions = list(self.action_history)
        
        if action_type:
            actions = [a for a in actions if a.content["action_type"] == action_type]
        
        if not actions:
            return 0.0
        
        successes = sum(1 for a in actions if a.content["success"])
        return successes / len(actions)
    
    # ─── Métodos de Memoria de Contexto/Preferencias ────────────────────────────
    
    def add_preference(self, key: str, value: Any):
        """Agregar preferencia del usuario."""
        self.user_profile.add_preference(key, value)
        self.user_profile.update_last_seen()
        self._save_user_profile()
        
        # También guardar como memoria
        memory_id = hashlib.md5(f"preference_{key}_{time.time()}".encode()).hexdigest()[:16]
        
        entry = MemoryEntry(
            id=memory_id,
            memory_type=MemoryType.PREFERENCE,
            content={
                "key": key,
                "value": value
            },
            timestamp=datetime.now(),
            importance=0.7,  # Preferencias son importantes
            tags=["preference", key]
        )
        
        self._save_memory(entry)
        logger.debug(f"Added preference: {key} = {value}")
    
    def get_preference(self, key: str, default: Any = None) -> Any:
        """Obtener preferencia del usuario."""
        return self.user_profile.preferences.get(key, default)
    
    def add_pattern(self, user_input: str, assistant_response: str):
        """Agregar patrón de interacción."""
        self.user_profile.add_interaction(user_input, assistant_response)
        self.user_profile.update_last_seen()
        self._save_user_profile()
        
        # Guardar como memoria de patrón
        memory_id = hashlib.md5(f"pattern_{user_input}_{time.time()}".encode()).hexdigest()[:16]
        
        entry = MemoryEntry(
            id=memory_id,
            memory_type=MemoryType.PATTERN,
            content={
                "user_input": user_input,
                "assistant_response": assistant_response
            },
            timestamp=datetime.now(),
            importance=0.6,
            tags=["pattern", "interaction"]
        )
        
        self._save_memory(entry)
        logger.debug(f"Added pattern: {user_input[:50]}... → {assistant_response[:50]}...")
    
    def find_similar_patterns(self, user_input: str, threshold: float = 0.7) -> List[str]:
        """Encontrar patrones similares (simplificado)."""
        patterns = self.user_profile.interaction_patterns
        
        # Búsqueda simple por palabras clave
        input_words = set(user_input.lower().split())
        similar = []
        
        for pattern, responses in patterns.items():
            pattern_words = set(pattern.lower().split())
            similarity = len(input_words & pattern_words) / max(len(input_words), 1)
            
            if similarity >= threshold and responses:
                similar.extend(responses[-3:])  # Últimas 3 respuestas
        
        return similar
    
    # ─── Métodos de Memoria Episódica ───────────────────────────────────────────
    
    def add_episodic_memory(self, event_type: str, description: str, 
                           metadata: Dict[str, Any] = None, importance: float = 0.8):
        """Agregar memoria episódica (eventos importantes)."""
        memory_id = hashlib.md5(f"episode_{event_type}_{time.time()}".encode()).hexdigest()[:16]
        
        entry = MemoryEntry(
            id=memory_id,
            memory_type=MemoryType.EPISODIC,
            content={
                "event_type": event_type,
                "description": description,
                "metadata": metadata or {},
                "user_id": self.user_id
            },
            timestamp=datetime.now(),
            importance=importance,
            tags=["episodic", event_type, "important"],
            expires=datetime.now() + timedelta(days=30)  # Expira después de 30 días
        )
        
        self._save_memory(entry)
        logger.info(f"Added episodic memory: {event_type} - {description[:50]}...")
    
    def get_recent_episodes(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Obtener episodios recientes."""
        return self._query_memories(
            memory_type=MemoryType.EPISODIC,
            limit=limit,
            order_by="timestamp DESC"
        )
    
    # ─── Métodos de Sistema ─────────────────────────────────────────────────────
    
    def add_system_memory(self, component: str, state: Dict[str, Any], 
                         importance: float = 0.4):
        """Agregar memoria del estado del sistema."""
        memory_id = hashlib.md5(f"system_{component}_{time.time()}".encode()).hexdigest()[:16]
        
        entry = MemoryEntry(
            id=memory_id,
            memory_type=MemoryType.SYSTEM,
            content={
                "component": component,
                "state": state,
                "user_id": self.user_id
            },
            timestamp=datetime.now(),
            importance=importance,
            tags=["system", component],
            expires=datetime.now() + timedelta(hours=24)  # Estado del sistema expira en 24h
        )
        
        self._save_memory(entry)
        logger.debug(f"Added system memory: {component}")
    
    # ─── Métodos de Base de Datos ───────────────────────────────────────────────
    
    def _save_memory(self, entry: MemoryEntry):
        """Guardar entrada de memoria en la base de datos."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO memories 
                (id, user_id, memory_type, content, timestamp, importance, tags, expires)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                entry.id,
                self.user_id,
                entry.memory_type.value,
                json.dumps(entry.content),
                entry.timestamp.isoformat(),
                entry.importance,
                json.dumps(entry.tags),
                entry.expires.isoformat() if entry.expires else None
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error saving memory: {e}")
    
    def _query_memories(self, memory_type: Optional[MemoryType] = None,
                       tags: Optional[List[str]] = None,
                       start_time: Optional[datetime] = None,
                       end_time: Optional[datetime] = None,
                       min_importance: float = 0.0,
                       limit: int = 100,
                       order_by: str = "timestamp DESC") -> List[Dict[str, Any]]:
        """Consultar memorias con filtros."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            query = "SELECT * FROM memories WHERE user_id = ?"
            params = [self.user_id]
            
            if memory_type:
                query += " AND memory_type = ?"
                params.append(memory_type.value)
            
            if tags:
                tag_conditions = []
                for tag in tags:
                    tag_conditions.append("tags LIKE ?")
                    params.append(f'%"{tag}"%')
                query += " AND (" + " OR ".join(tag_conditions) + ")"
            
            if start_time:
                query += " AND timestamp >= ?"
                params.append(start_time.isoformat())
            
            if end_time:
                query += " AND timestamp <= ?"
                params.append(end_time.isoformat())
            
            query += " AND importance >= ?"
            params.append(min_importance)
            
            # Filtrar expirados
            query += " AND (expires IS NULL OR expires > ?)"
            params.append(datetime.now().isoformat())
            
            query += f" ORDER BY {order_by} LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()
            
            # Convertir a diccionarios
            memories = []
            for row in rows:
                try:
                    entry = MemoryEntry(
                        id=row[0],
                        memory_type=MemoryType(row[2]),
                        content=json.loads(row[3]),
                        timestamp=datetime.fromisoformat(row[4]),
                        importance=row[5],
                        tags=json.loads(row[6]) if row[6] else [],
                        expires=datetime.fromisoformat(row[7]) if row[7] else None
                    )
                    memories.append(entry.to_dict())
                except Exception as e:
                    logger.error(f"Error parsing memory row: {e}")
                    continue
            
            return memories
            
        except Exception as e:
            logger.error(f"Error querying memories: {e}")
            return []
    
    # ─── Métodos de Mantenimiento ───────────────────────────────────────────────
    
    def cleanup_expired(self):
        """Limpiar memorias expiradas."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute(
                'DELETE FROM memories WHERE expires IS NOT NULL AND expires < ?',
                (datetime.now().isoformat(),)
            )
            
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
            
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} expired memories")
            
            return deleted
            
        except Exception as e:
            logger.error(f"Error cleaning up expired memories: {e}")
            return 0
    
    def get_statistics(self) -> Dict[str, Any]:
        """Obtener estadísticas de la memoria."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Contar por tipo
            cursor.execute(
                'SELECT memory_type, COUNT(*) FROM memories WHERE user_id = ? GROUP BY memory_type',
                (self.user_id,)
            )
            type_counts = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Memoria total
            cursor.execute(
                'SELECT COUNT(*) FROM memories WHERE user_id = ?',
                (self.user_id,)
            )
            total_memories = cursor.fetchone()[0]
            
            # Importancia promedio
            cursor.execute(
                'SELECT AVG(importance) FROM memories WHERE user_id = ?',
                (self.user_id,)
            )
            avg_importance = cursor.fetchone()[0] or 0.0
            
            conn.close()
            
            return {
                "total_memories": total_memories,
                "type_counts": type_counts,
                "avg_importance": avg_importance,
                "conversation_buffer_size": len(self.conversation_buffer),
                "action_history_size": len(self.action_history),
                "user_preferences_count": len(self.user_profile.preferences),
                "user_patterns_count": len(self.user_profile.interaction_patterns),
                "user_trust_level": self.user_profile.trust_level,
                "last_seen": self.user_profile.last_seen.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {}
    
    # ─── Métodos de Contexto para IA ────────────────────────────────────────────
    
    def get_context_for_ai(self) -> str:
        """Generar contexto completo para el modelo de IA."""
        context_parts = []
        
        # 1. Preferencias del usuario
        if self.user_profile.preferences:
            prefs = ", ".join(f"{k}: {v}" for k, v in self.user_profile.preferences.items()[:5])
            context_parts.append(f"Preferencias del usuario: {prefs}")
        
        # 2. Patrones de interacción recientes
        recent_patterns = list(self.user_profile.interaction_patterns.items())[-3:]
        if recent_patterns:
            patterns = "; ".join(f"{k}→{v[-1]}" for k, v in recent_patterns)
            context_parts.append(f"Patrones recientes: {patterns}")
        
        # 3. Comandos frecuentes
        top_commands = sorted(
            self.user_profile.frequent_commands.items(),
            key=lambda x: x[1],
            reverse=True
        )[:3]
        if top_commands:
            commands = ", ".join(f"{cmd}({count})" for cmd, count in top_commands)
            context_parts.append(f"Comandos frecuentes: {commands}")
        
        # 4. Acciones recientes exitosas
        recent_actions = self.get_action_history(limit=5)
        if recent_actions:
            actions = "; ".join(
                f"{a['action_type']}: {a['command'][:30]}"
                for a in recent_actions if a['success']
            )
            if actions:
                context_parts.append(f"Acciones recientes: {actions}")
        
        # 5. Contexto de conversación reciente
        conv_context = self.get_conversation_context(window_minutes=60)
        if conv_context:
            context_parts.append(f"Conversación reciente:\n{conv_context}")
        
        return "\n\n".join(context_parts)
    
    def update_trust_level(self, success: bool):
        """Actualizar nivel de confianza basado en éxito/failure."""
        change = 0.05 if success else -0.1
        self.user_profile.trust_level = max(0.0, min(1.0, self.user_profile.trust_level + change))
        self.user_profile.update_last_seen()
        self._save_user_profile()
        
        logger.debug(f"Updated trust level to {self.user_profile.trust_level:.2f}")


# ─── Singleton para acceso global ──────────────────────────────────────────────

_memory_instance = None

def get_memory(user_id: str = "default") -> PersistentMemory:
    """Obtener instancia singleton de memoria."""
    global _memory_instance
    
    if _memory_instance is None or _memory_instance.user_id != user_id:
        _memory_instance = PersistentMemory(user_id)
    
    return _memory_instance


# ─── Funciones de utilidad ─────────────────────────────────────────────────────

def test_memory_system():
    """Probar el sistema de memoria."""
    print("🧠 Probando sistema de memoria persistente...")
    
    memory = get_memory("test_user")
    
    # Agregar algunas memorias
    memory.add_conversation("user", "Hola Sylix, ¿cómo estás?")
    memory.add_conversation("assistant", "¡Hola! Estoy bien, ¿y tú?")
    
    memory.add_action("bash", "ls -la", {"status": "success"}, success=True)
    memory.add_action("file", "read config.txt", {"status": "error"}, success=False)
    
    memory.add_preference("theme", "dark")
    memory.add_preference("language", "español")
    
    memory.add_pattern("¿Qué hora es?", "Son las 15:30")
    
    memory.add_episodic_memory(
        "first_interaction",
        "Primera interacción con el usuario test_user",
        {"mood": "positive"}
    )
    
    # Mostrar estadísticas
    stats = memory.get_statistics()
    print("📊 Estadísticas de memoria:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Mostrar contexto para IA
    context = memory.get_context_for_ai()
    print("\n🧠 Contexto para IA:")
    print(context[:500] + "..." if len(context) > 500 else context)
    
    print("\n✅ Sistema de memoria probado exitosamente!")


if __name__ == "__main__":
    test_memory_system()