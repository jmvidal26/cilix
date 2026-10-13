#!/usr/bin/env python3
"""
Módulo de Memoria de Cilix
==========================
Persistencia local (SQLite) de conversaciones y preferencias del usuario.
100%% offline. Base para dar continuidad entre sesiones sin consumir RAM de
más: solo se cargan en contexto los recuerdos recientes.
"""

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MemoryStore:
    """Almacén de memoria a corto/largo plazo respaldado por SQLite."""

    def __init__(self, db_path: Optional[str] = None):
        # Por defecto en ~/.config/cilix/memory.db
        if db_path is None:
            base = Path.home() / ".config" / "cilix"
            base.mkdir(parents=True, exist_ok=True)
            db_path = str(base / "memory.db")
        self.db_path = db_path
        self._init_db()
        logger.info("💾 Memoria inicializada en %s", db_path)

    def _init_db(self) -> None:
        """Crea las tablas si no existen."""
        with sqlite3.connect(self.db_path) as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session TEXT NOT NULL,
                    role   TEXT NOT NULL,
                    content TEXT NOT NULL,
                    mode   TEXT,
                    emotion TEXT,
                    ts     REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS facts (
                    key   TEXT PRIMARY KEY,
                    value TEXT,
                    ts    REAL
                );
                CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session, ts);
                """
            )

    def add_message(self, session: str, role: str, content: str,
                    mode: str = "Ri", emotion: str = "neutral") -> None:
        """Guarda un mensaje del intercambio."""
        try:
            with sqlite3.connect(self.db_path) as con:
                con.execute(
                    "INSERT INTO messages (session, role, content, mode, emotion, ts)"
                    " VALUES (?,?,?,?,?,?)",
                    (session, role, content, mode, emotion, time.time()),
                )
        except sqlite3.Error as exc:  # noqa: BLE001
            logger.error("❌ Error guardando mensaje: %s", exc)

    def recent_messages(self, session: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Devuelve los mensajes más recientes de una sesión."""
        try:
            with sqlite3.connect(self.db_path) as con:
                con.row_factory = sqlite3.Row
                rows = con.execute(
                    "SELECT role, content, mode, emotion, ts FROM messages"
                    " WHERE session=? ORDER BY ts DESC LIMIT ?",
                    (session, limit),
                ).fetchall()
            return [dict(r) for r in reversed(rows)]
        except sqlite3.Error as exc:  # noqa: BLE001
            logger.error("❌ Error leyendo historial: %s", exc)
            return []

    def remember_fact(self, key: str, value: str) -> None:
        """Guarda/actualiza un hecho persistente (nombre, preferencias...)."""
        try:
            with sqlite3.connect(self.db_path) as con:
                con.execute(
                    "INSERT INTO facts (key, value, ts) VALUES (?,?,?)"
                    " ON CONFLICT(key) DO UPDATE SET value=excluded.value, ts=excluded.ts",
                    (key, value, time.time()),
                )
        except sqlite3.Error as exc:  # noqa: BLE001
            logger.error("❌ Error guardando hecho: %s", exc)

    def get_fact(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Recupera un hecho guardado."""
        try:
            with sqlite3.connect(self.db_path) as con:
                row = con.execute(
                    "SELECT value FROM facts WHERE key=?", (key,)
                ).fetchone()
            return row[0] if row else default
        except sqlite3.Error as exc:  # noqa: BLE001
            logger.error("❌ Error leyendo hecho: %s", exc)
            return default

    def prune(self, retention_days: int = 30) -> int:
        """Elimina mensajes más antiguos al período de retención."""
        cutoff = time.time() - retention_days * 86400
        try:
            with sqlite3.connect(self.db_path) as con:
                cur = con.execute("DELETE FROM messages WHERE ts < ?", (cutoff,))
                return cur.rowcount
        except sqlite3.Error as exc:  # noqa: BLE001
            logger.error("❌ Error depurando memoria: %s", exc)
            return 0
