"""
advanced_features.py — Integración de características avanzadas para Sylix OS Core

Integra:
1. Memoria persistente (siempre activa)
2. Monitor de actividad (opcional)
3. Pensamiento proactivo (opcional)

Este módulo proporciona una API unificada para las tres características.
"""

import os
import json
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Callable
import logging

# Importar módulos de características avanzadas
try:
    from memory import get_memory, PersistentMemory
    from activity_monitor import get_activity_monitor, ActivityMonitor
    from proactive_thinking import get_proactive_thinker, ProactiveThinker
    IMPORT_SUCCESS = True
except ImportError as e:
    logging.error(f"Error importing advanced features modules: {e}")
    IMPORT_SUCCESS = False

logger = logging.getLogger("sylix.advanced")

class AdvancedFeatures:
    """Gestor unificado de características avanzadas."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        
        # Estado de características
        self.features = {
            "memory": {
                "enabled": True,  # Siempre activa
                "instance": None,
                "description": "Memoria persistente del usuario"
            },
            "activity_monitor": {
                "enabled": self.config.get("activity_monitor_enabled", False),
                "instance": None,
                "description": "Monitor de actividad del sistema"
            },
            "proactive_thinking": {
                "enabled": self.config.get("proactive_thinking_enabled", False),
                "instance": None,
                "description": "Pensamiento proactivo y sugerencias"
            }
        }
        
        # Contexto compartido
        self.shared_context = {}
        self.context_lock = threading.Lock()
        
        # Inicializar instancias
        self._initialize_instances()
        
        # Hilos de integración
        self.integration_thread = None
        self.is_running = False
        
        logger.info("Advanced Features initialized")
    
    def _initialize_instances(self):
        """Inicializar instancias de los módulos."""
        if not IMPORT_SUCCESS:
            logger.error("Cannot initialize advanced features due to import errors")
            return
        
        try:
            # Memoria persistente (siempre activa)
            self.features["memory"]["instance"] = get_memory()
            logger.info("Memory system initialized")
            
            # Monitor de actividad (opcional)
            if self.features["activity_monitor"]["enabled"]:
                self.features["activity_monitor"]["instance"] = get_activity_monitor(enabled=True)
                self.features["activity_monitor"]["instance"].start_monitoring()
                logger.info("Activity monitor initialized and started")
            
            # Pensamiento proactivo (opcional)
            if self.features["proactive_thinking"]["enabled"]:
                self.features["proactive_thinking"]["instance"] = get_proactive_thinker(enabled=True)
                self.features["proactive_thinking"]["instance"].start_thinking()
                logger.info("Proactive thinking initialized and started")
                
        except Exception as e:
            logger.error(f"Error initializing advanced features: {e}")
    
    # ─── Métodos de Control de Características ────────────────────────────────
    
    def enable_feature(self, feature_name: str) -> bool:
        """Habilitar una característica específica."""
        if feature_name not in self.features:
            logger.error(f"Unknown feature: {feature_name}")
            return False
        
        feature = self.features[feature_name]
        
        if feature["enabled"]:
            logger.warning(f"Feature {feature_name} is already enabled")
            return True
        
        feature["enabled"] = True
        
        try:
            if feature_name == "activity_monitor":
                if not feature["instance"]:
                    feature["instance"] = get_activity_monitor(enabled=True)
                feature["instance"].enable()
                feature["instance"].start_monitoring()
                logger.info(f"Enabled {feature_name}")
                
            elif feature_name == "proactive_thinking":
                if not feature["instance"]:
                    feature["instance"] = get_proactive_thinker(enabled=True)
                feature["instance"].enable()
                feature["instance"].start_thinking()
                logger.info(f"Enabled {feature_name}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error enabling feature {feature_name}: {e}")
            feature["enabled"] = False
            return False
    
    def disable_feature(self, feature_name: str) -> bool:
        """Deshabilitar una característica específica."""
        if feature_name not in self.features:
            logger.error(f"Unknown feature: {feature_name}")
            return False
        
        if feature_name == "memory":
            logger.warning("Cannot disable memory system (always enabled)")
            return False
        
        feature = self.features[feature_name]
        
        if not feature["enabled"]:
            logger.warning(f"Feature {feature_name} is already disabled")
            return True
        
        feature["enabled"] = False
        
        try:
            if feature_name == "activity_monitor" and feature["instance"]:
                feature["instance"].stop_monitoring()
                feature["instance"].disable()
                logger.info(f"Disabled {feature_name}")
                
            elif feature_name == "proactive_thinking" and feature["instance"]:
                feature["instance"].stop_thinking()
                feature["instance"].disable()
                logger.info(f"Disabled {feature_name}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error disabling feature {feature_name}: {e}")
            return False
    
    def get_feature_status(self, feature_name: Optional[str] = None) -> Dict[str, Any]:
        """Obtener estado de características."""
        if feature_name:
            if feature_name not in self.features:
                return {"error": f"Unknown feature: {feature_name}"}
            
            feature = self.features[feature_name]
            status = {
                "enabled": feature["enabled"],
                "description": feature["description"]
            }
            
            if feature["instance"]:
                if feature_name == "memory":
                    status.update(feature["instance"].get_statistics())
                elif feature_name == "activity_monitor":
                    status.update(feature["instance"].get_status())
                elif feature_name == "proactive_thinking":
                    status.update(feature["instance"].get_statistics())
            
            return status
        
        # Estado de todas las características
        all_status = {}
        for name, feature in self.features.items():
            all_status[name] = {
                "enabled": feature["enabled"],
                "description": feature["description"],
                "has_instance": feature["instance"] is not None
            }
        
        return all_status
    
    # ─── Métodos de Memoria Persistente ────────────────────────────────────────
    
    def add_conversation(self, role: str, content: str, metadata: Optional[Dict] = None):
        """Agregar conversación a la memoria."""
        if not self.features["memory"]["enabled"] or not self.features["memory"]["instance"]:
            return
        
        try:
            self.features["memory"]["instance"].add_conversation(role, content, metadata)
        except Exception as e:
            logger.error(f"Error adding conversation to memory: {e}")
    
    def add_action(self, action_type: str, command: str, result: Dict[str, Any], 
                   success: bool = True, importance: float = 0.5):
        """Agregar acción a la memoria."""
        if not self.features["memory"]["enabled"] or not self.features["memory"]["instance"]:
            return
        
        try:
            self.features["memory"]["instance"].add_action(
                action_type, command, result, success, importance
            )
            
            # Si el pensamiento proactivo está habilitado, actualizar contexto
            if self.features["proactive_thinking"]["enabled"] and self.features["proactive_thinking"]["instance"]:
                self._update_proactive_context({
                    "action_type": action_type,
                    "command": command,
                    "success": success,
                    "result": result
                })
                
        except Exception as e:
            logger.error(f"Error adding action to memory: {e}")
    
    def get_conversation_context(self, window_minutes: int = 60) -> str:
        """Obtener contexto de conversación."""
        if not self.features["memory"]["enabled"] or not self.features["memory"]["instance"]:
            return ""
        
        try:
            return self.features["memory"]["instance"].get_conversation_context(window_minutes)
        except Exception as e:
            logger.error(f"Error getting conversation context: {e}")
            return ""
    
    def get_user_preferences(self) -> Dict[str, Any]:
        """Obtener preferencias del usuario."""
        if not self.features["memory"]["enabled"] or not self.features["memory"]["instance"]:
            return {}
        
        try:
            memory = self.features["memory"]["instance"]
            return {
                "preferences": memory.user_profile.preferences,
                "frequent_commands": memory.user_profile.frequent_commands,
                "trust_level": memory.user_profile.trust_level
            }
        except Exception as e:
            logger.error(f"Error getting user preferences: {e}")
            return {}
    
    # ─── Métodos de Monitor de Actividad ──────────────────────────────────────
    
    def update_activity_context(self, activity_data: Dict[str, Any]):
        """Actualizar contexto de actividad."""
        if not self.features["activity_monitor"]["enabled"] or not self.features["activity_monitor"]["instance"]:
            return
        
        try:
            monitor = self.features["activity_monitor"]["instance"]
            
            # Actualizar monitor de actividad
            if "window_info" in activity_data:
                monitor.log_window_focus(activity_data["window_info"])
            
            if "application_use" in activity_data:
                app_data = activity_data["application_use"]
                monitor.log_application_use(
                    app_data.get("app_name", "unknown"),
                    app_data.get("action", "used"),
                    app_data.get("details", {})
                )
            
            if "user_interaction" in activity_data:
                interaction_data = activity_data["user_interaction"]
                monitor.log_user_interaction(
                    interaction_data.get("type", "interaction"),
                    interaction_data.get("details", {})
                )
            
            # Actualizar contexto compartido
            with self.context_lock:
                self.shared_context.update(activity_data)
                
                # Actualizar pensamiento proactivo si está habilitado
                if self.features["proactive_thinking"]["enabled"] and self.features["proactive_thinking"]["instance"]:
                    self.features["proactive_thinking"]["instance"].update_context(activity_data)
                    
        except Exception as e:
            logger.error(f"Error updating activity context: {e}")
    
    def get_activity_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Obtener resumen de actividad."""
        if not self.features["activity_monitor"]["enabled"] or not self.features["activity_monitor"]["instance"]:
            return {"error": "Activity monitor disabled"}
        
        try:
            return self.features["activity_monitor"]["instance"].get_activity_summary(hours)
        except Exception as e:
            logger.error(f"Error getting activity summary: {e}")
            return {"error": str(e)}
    
    def get_user_patterns(self) -> Dict[str, Any]:
        """Obtener patrones de uso del usuario."""
        if not self.features["activity_monitor"]["enabled"] or not self.features["activity_monitor"]["instance"]:
            return {"error": "Activity monitor disabled"}
        
        try:
            return self.features["activity_monitor"]["instance"].get_user_patterns()
        except Exception as e:
            logger.error(f"Error getting user patterns: {e}")
            return {"error": str(e)}
    
    # ─── Métodos de Pensamiento Proactivo ────────────────────────────────────
    
    def _update_proactive_context(self, context_data: Dict[str, Any]):
        """Actualizar contexto del pensador proactivo."""
        if not self.features["proactive_thinking"]["enabled"] or not self.features["proactive_thinking"]["instance"]:
            return
        
        try:
            self.features["proactive_thinking"]["instance"].update_context(context_data)
        except Exception as e:
            logger.error(f"Error updating proactive context: {e}")
    
    def get_proactive_suggestions(self, limit: int = 3) -> List[Dict[str, Any]]:
        """Obtener sugerencias proactivas."""
        if not self.features["proactive_thinking"]["enabled"] or not self.features["proactive_thinking"]["instance"]:
            return []
        
        try:
            return self.features["proactive_thinking"]["instance"].get_top_thoughts(limit)
        except Exception as e:
            logger.error(f"Error getting proactive suggestions: {e}")
            return []
    
    def acknowledge_suggestion(self, suggestion_id: str, user_response: Optional[str] = None) -> bool:
        """Reconocer/responder a una sugerencia."""
        if not self.features["proactive_thinking"]["enabled"] or not self.features["proactive_thinking"]["instance"]:
            return False
        
        try:
            return self.features["proactive_thinking"]["instance"].acknowledge_thought(
                suggestion_id, user_response
            )
        except Exception as e:
            logger.error(f"Error acknowledging suggestion: {e}")
            return False
    
    def add_custom_rule(self, rule_data: Dict[str, Any]) -> bool:
        """Agregar regla personalizada para pensamiento proactivo."""
        if not self.features["proactive_thinking"]["enabled"] or not self.features["proactive_thinking"]["instance"]:
            return False
        
        try:
            return self.features["proactive_thinking"]["instance"].add_custom_rule(rule_data)
        except Exception as e:
            logger.error(f"Error adding custom rule: {e}")
            return False
    
    # ─── Métodos de Integración ───────────────────────────────────────────────
    
    def start_integration(self):
        """Iniciar integración de características."""
        if self.is_running:
            logger.warning("Integration already running")
            return
        
        self.is_running = True
        self.integration_thread = threading.Thread(
            target=self._integration_loop,
            daemon=True
        )
        self.integration_thread.start()
        
        logger.info("Advanced features integration started")
    
    def stop_integration(self):
        """Detener integración de características."""
        self.is_running = False
        
        if self.integration_thread:
            self.integration_thread.join(timeout=5)
        
        logger.info("Advanced features integration stopped")
    
    def _integration_loop(self):
        """Loop de integración que conecta las características."""
        while self.is_running:
            try:
                # 1. Sincronizar contexto compartido
                self._sync_shared_context()
                
                # 2. Procesar sugerencias proactivas basadas en actividad
                self._process_activity_based_suggestions()
                
                # 3. Aprender de patrones
                self._learn_from_patterns()
                
                # Esperar antes del próximo ciclo
                time.sleep(30)  # Cada 30 segundos
                
            except Exception as e:
                logger.error(f"Error in integration loop: {e}")
                time.sleep(60)  # Esperar más en caso de error
    
    def _sync_shared_context(self):
        """Sincronizar contexto entre características."""
        # Esta función se encarga de compartir información entre
        # memoria, actividad y pensamiento proactivo
        
        # Por ejemplo: si el monitor de actividad detecta un patrón,
        # actualizar la memoria y generar pensamientos proactivos
        
        pass  # Implementación detallada iría aquí
    
    def _process_activity_based_suggestions(self):
        """Procesar sugerencias basadas en actividad."""
        if (not self.features["activity_monitor"]["enabled"] or 
            not self.features["proactive_thinking"]["enabled"]):
            return
        
        # Obtener actividad reciente
        activity_summary = self.get_activity_summary(hours=1)
        
        # Generar contexto para pensamiento proactivo
        if "event_counts" in activity_summary:
            self._update_proactive_context({
                "recent_activity": activity_summary["event_counts"],
                "top_applications": activity_summary.get("top_applications", [])
            })
    
    def _learn_from_patterns(self):
        """Aprender de patrones para mejorar todas las características."""
        # Esta función analiza datos de todas las características
        # para encontrar patrones y mejorar el sistema
        
        # Por ejemplo: si la memoria muestra que el usuario siempre
        # ejecuta ciertos comandos después de otros, aprender ese patrón
        
        pass  # Implementación detallada iría aquí
    
    # ─── Métodos de Utilidad ─────────────────────────────────────────────────
    
    def get_context_for_ai(self) -> str:
        """Generar contexto unificado para el modelo de IA."""
        context_parts = []
        
        # 1. Contexto de memoria
        if self.features["memory"]["enabled"] and self.features["memory"]["instance"]:
            try:
                memory_context = self.features["memory"]["instance"].get_context_for_ai()
                if memory_context:
                    context_parts.append("🧠 MEMORIA DEL USUARIO:")
                    context_parts.append(memory_context)
            except Exception as e:
                logger.error(f"Error getting memory context: {e}")
        
        # 2. Patrones de actividad reciente
        if self.features["activity_monitor"]["enabled"]:
            try:
                patterns = self.get_user_patterns()
                if patterns and "error" not in patterns:
                    context_parts.append("👀 PATRONES RECIENTES:")
                    if patterns.get("favorite_apps"):
                        apps = ", ".join([app["name"] for app in patterns["favorite_apps"][:3]])
                        context_parts.append(f"Aplicaciones favoritas: {apps}")
            except Exception as e:
                logger.error(f"Error getting activity patterns: {e}")
        
        # 3. Sugerencias proactivas pendientes
        if self.features["proactive_thinking"]["enabled"]:
            try:
                suggestions = self.get_proactive_suggestions(limit=2)
                if suggestions:
                    context_parts.append("💡 SUGERENCIAS PROACTIVAS:")
                    for sug in suggestions:
                        msg = sug["content"].get("message", "Sugerencia")
                        context_parts.append(f"- {msg}")
            except Exception as e:
                logger.error(f"Error getting proactive suggestions: {e}")
        
        return "\n\n".join(context_parts) if context_parts else ""
    
    def get_system_stats(self) -> Dict[str, Any]:
        """Obtener estadísticas del sistema de características avanzadas."""
        stats = {
            "timestamp": datetime.now().isoformat(),
            "features": self.get_feature_status(),
            "integration_running": self.is_running
        }
        
        # Estadísticas específicas por característica
        for feature_name, feature in self.features.items():
            if feature["enabled"] and feature["instance"]:
                try:
                    if feature_name == "memory":
                        stats["memory_stats"] = feature["instance"].get_statistics()
                    elif feature_name == "activity_monitor":
                        stats["activity_stats"] = feature["instance"].get_status()
                    elif feature_name == "proactive_thinking":
                        stats["thinking_stats"] = feature["instance"].get_statistics()
                except Exception as e:
                    logger.error(f"Error getting stats for {feature_name}: {e}")
        
        return stats
    
    def cleanup(self, days_to_keep: int = 7):
        """Limpiar datos antiguos de todas las características."""
        results = {}
        
        # Limpiar memoria
        if self.features["memory"]["enabled"] and self.features["memory"]["instance"]:
            try:
                results["memory"] = self.features["memory"]["instance"].cleanup_expired()
            except Exception as e:
                logger.error(f"Error cleaning memory: {e}")
                results["memory_error"] = str(e)
        
        # Limpiar actividad
        if self.features["activity_monitor"]["enabled"] and self.features["activity_monitor"]["instance"]:
            try:
                results["activity"] = self.features["activity_monitor"]["instance"].cleanup_old_data(days_to_keep)
            except Exception as e:
                logger.error(f"Error cleaning activity data: {e}")
                results["activity_error"] = str(e)
        
        # Limpiar pensamiento proactivo
        if self.features["proactive_thinking"]["enabled"] and self.features["proactive_thinking"]["instance"]:
            try:
                results["proactive"] = self.features["proactive_thinking"]["instance"].cleanup_old_data(days_to_keep)
            except Exception as e:
                logger.error(f"Error cleaning proactive data: {e}")
                results["proactive_error"] = str(e)
        
        logger.info(f"Cleanup completed: {results}")
        return results


# ─── Singleton para acceso global ──────────────────────────────────────────────

_advanced_features_instance = None

def get_advanced_features(config: Optional[Dict[str, Any]] = None) -> AdvancedFeatures:
    """Obtener instancia singleton de características avanzadas."""
    global _advanced_features_instance
    
    if _advanced_features_instance is None:
        _advanced_features_instance = AdvancedFeatures(config)
    
    return _advanced_features_instance


# ─── Funciones de Utilidad ───────────────────────────────────────────────────

def test_advanced_features():
    """Probar el sistema integrado de características avanzadas."""
    print("🚀 Probando características avanzadas integradas...")
    
    # Configurar características
    config = {
        "activity_monitor_enabled": True,
        "proactive_thinking_enabled": True
    }
    
    features = get_advanced_features(config)
    
    # Habilitar características
    print("1. Habilitando características...")
    features.enable_feature("activity_monitor")
    features.enable_feature("proactive_thinking")
    
    # Probar memoria
    print("\n2. Probando memoria persistente...")
    features.add_conversation("user", "Hola, estoy probando el sistema")
    features.add_conversation("assistant", "¡Hola! Estoy aquí para ayudarte")
    
    features.add_action("bash", "ls -la", {"status": "success"}, success=True)
    
    # Probar contexto para IA
    print("\n3. Generando contexto para IA...")
    context = features.get_context_for_ai()
    print(f"   Contexto generado ({len(context)} caracteres)")
    if context:
        print(f"   Preview: {context[:200]}...")
    
    # Obtener sugerencias proactivas
    print("\n4. Obteniendo sugerencias proactivas...")
    suggestions = features.get_proactive_suggestions()
    print(f"   Sugerencias encontradas: {len(suggestions)}")
    
    # Obtener estadísticas
    print("\n5. Obteniendo estadísticas del sistema...")
    stats = features.get_system_stats()
    print(f"   Características activas: {sum(1 for f in stats['features'].values() if f['enabled'])}")
    
    # Estado final
    print(f"\n6. Estado final:")
    for feature_name, feature in stats["features"].items():
        status = "✅ ACTIVA" if feature["enabled"] else "❌ INACTIVA"
        print(f"   {feature_name}: {status}")
    
    # Limpiar
    features.stop_integration()
    
    print("\n✅ Características avanzadas probadas exitosamente!")


if __name__ == "__main__":
    # Para pruebas, ejecutar con logging básico
    logging.basicConfig(level=logging.INFO)
    
    if IMPORT_SUCCESS:
        test_advanced_features()
    else:
        print("❌ No se pueden probar las características avanzadas debido a errores de importación")