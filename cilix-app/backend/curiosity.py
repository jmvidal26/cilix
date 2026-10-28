#!/usr/bin/env python3
"""
Motor de curiosidad de Cilix — "aprende cosas al azar y se forma opiniones"
===========================================================================
Cilix busca de vez en cuando un tema aleatorio en la web, se queda con un
dato curioso y lo convierte en parte de su personalidad:

  · guarda el hallazgo en ~/.config/cilix/curiosity.json (sobrevive reinicios)
  · deriva un "tema que le llama la atención" y una opinión propia
  · ambos se inyectan en el prompt como una línea corta (ver voice_layer)

Búsqueda sin API key ni dependencias nuevas (solo httpx):
  1. Google (HTML). Google suele servir una página con JavaScript, así que
     si no hay resultados se recuerda el fallo y se pasa al siguiente.
  2. Bing (HTML, sí viene renderizado en servidor).
  3. Wikipedia (API pública): siempre disponible, ideal para datos raros.

Diseño de bajo consumo: nada de navegador, nada de modelos; una petición
HTTP por búsqueda y un JSON pequeño. Coste en reposo: 0.
"""

from __future__ import annotations

import asyncio
import hashlib
import html as _html
import json
import logging
import os
import random
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

STORE_PATH = Path.home() / ".config" / "cilix" / "curiosity.json"
MAX_LEARNED = 120

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.6",
}

# Temas semilla: cosas variadas que despiertan curiosidad (no solo tecnología).
SEED_TOPICS = [
    "curiosidades de los pulpos", "cómo se forman los agujeros negros",
    "historia del synthwave", "por qué ronronean los gatos",
    "la inteligencia de los cuervos", "historia de los salones arcade",
    "volcanes submarinos", "la vida en las fosas abisales",
    "arquitectura brutalista", "el arte de Remedios Varo",
    "los mensajes de las sondas Voyager", "cómo funciona el GPS",
    "la historia del café", "los mapas antiguos",
    "las auroras boreales", "los relojes mecánicos",
    "la inteligencia de los delfines", "el sonido de los planetas",
    "los fósiles más raros", "la historia de internet",
    "los memes de Linux", "la cocina de fermentación",
    "los tatuajes polinesios", "los trenes de levitación",
    "la música de los años 80", "los desiertos más secos",
    "animales que se regeneran", "la exploración de Marte",
    "los secretos del Titanic", "idiomas que están desapareciendo",
    "la fotografía analógica", "hongos bioluminiscentes",
    "ciudades flotantes", "la historia de la bicicleta",
    "récords de la naturaleza", "el arte del origami",
    "los satélites artificiales", "la química del pan",
    "los mitos nórdicos", "los volcanes de Islandia",
    "constelaciones olvidadas", "los inventos de Leonardo da Vinci",
    "la vida de las abejas", "túneles secretos de las ciudades",
    "la historia del té", "los robots de cocina",
    "la moda de los años 90", "pueblos abandonados de España",
    "la ciencia de los sueños", "los faros más antiguos",
    "la música de las ballenas", "los videojuegos de los 80",
    "la historia del chocolate", "los árboles más viejos del mundo",
]

# Señales para decidir si el hallazgo le gusta, le inquieta o le da igual.
POSITIVE = {
    "descubrimiento", "sorprendente", "fascinante", "bonito", "bello", "arte",
    "música", "amor", "curioso", "inteligente", "colorido", "brilla", "océano",
    "espacio", "animal", "historia", "invento", "ciencia", "cultura", "juego",
    "café", "gato", "pulpo", "abeja", "ballena", "naturaleza", "estrella",
    "planeta", "libro", "fotografía", "arquitectura", "danza", "risa",
}
NEGATIVE = {
    "guerra", "muerte", "extinción", "peligro", "veneno", "terror", "crisis",
    "contaminación", "enfermedad", "miedo", "cruel", "desastre", "tragedia",
    "colapso", "amenaza", "oscuro", "abandonado", "peste", "hambre",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

# Intenciones del chat relacionadas con la curiosidad.
_RECALL_RE = re.compile(
    r"qu[eé] (?:has|hab[ií]as) aprendido|tus (?:descubrimientos|curiosidades)|"
    r"qu[eé] sabes de tus b[uú]squedas|de qu[eé] te acuerdas de internet",
    re.I,
)
_VERB_RE = re.compile(
    r"\b(?:busca|b[uú]scame|investiga|aprende|descubre|curiosea|sorpr[eé]ndeme)\b",
    re.I,
)
# Sin estas señales, un simple "busca" se deja al buscador de archivos del SO.
_EXPLICIT_RE = re.compile(
    r"\b(?:curiosea|aprende\s+(?:algo|sobre|de)|descubre\s+algo|"
    r"investiga\s+(?:algo|sobre|acerca\s+de)|b[uú]scame\s+algo|"
    r"busca\s+en\s+(?:google|internet)|"
    r"busca\s+(?:algo\s+)?(?:random|aleatorio|sobre|acerca\s+de))\b",
    re.I,
)
_RANDOM_RE = re.compile(
    r"\b(?:random|aleatorio|al azar|nuevo|curioso|interesante|sorpr[eé]ndeme)\b",
    re.I,
)
_TOPIC_RE = re.compile(
    r"(?:busca|b[uú]scame|investiga|aprende|descubre|curiosea)\s+"
    r"(?:en\s+(?:google|internet)\s+)?"
    r"(?:sobre|acerca\s+de|de)?\s*(.+)$",
    re.I,
)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _plain(fragment: str) -> str:
    return _WS_RE.sub(" ", _html.unescape(_TAG_RE.sub(" ", fragment or ""))).strip()


_DATE_PREFIX_RE = re.compile(
    r"^\s*\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4}\s*[·\-–—|]?\s*", re.I)


def _clip_fact(text: str, limit: int = 180) -> str:
    """Recorta un snippet a 1-2 frases legibles (sin cortar a mitad de palabra)."""
    text = _WS_RE.sub(" ", (text or "").strip())
    text = _DATE_PREFIX_RE.sub("", text)
    text = re.sub(r"^(?:Ver más|Más información|Leer más)\s*", "", text, flags=re.I)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if "." in cut[60:]:
        cut = cut[:cut.rfind(".") + 1]
    else:
        cut = cut[:cut.rfind(" ")] + "…"
    return cut.strip()


def _short_topic(topic: str, limit: int = 52) -> str:
    t = re.sub(
        r"^(?:curiosidades|historia|secretos|misterios)\s+(?:de|del|sobre)\s+",
        "", topic.strip(), flags=re.I,
    )
    return (t[:limit].rstrip(" ,.;:") or topic)[:limit]


class CuriosityEngine:
    """Busca temas al azar y los convierte en rasgos de personalidad."""

    def __init__(self, store_path: Optional[Path] = None,
                 engine: str = "auto") -> None:
        self.store_path = Path(store_path) if store_path else STORE_PATH
        self.engine = (engine or "auto").lower()
        self._data: Dict[str, Any] = {"learned": [], "seen": []}
        self._google_ok_until = 0.0
        # Google Custom Search JSON API (opcional, la vía legítima y estable).
        self.google_key = os.getenv("CILIX_GOOGLE_API_KEY", "").strip()
        self.google_cx = os.getenv("CILIX_GOOGLE_CX", "").strip()
        self._lock = asyncio.Lock()
        self._load()

    # ── persistencia ─────────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("learned"), list):
                # Regenerar opiniones con la plantilla actual (por si cambió).
                for item in data["learned"]:
                    item["short"] = _short_topic(item.get("topic", ""))
                    item["opinion"] = self._opinion_for(
                        item.get("topic", ""), float(item.get("score", 0.0)))
                self._data = data
        except FileNotFoundError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("curiosity.json ilegible (%r); empiezo de cero", exc)

    def _save(self) -> None:
        try:
            self.store_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.store_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(self.store_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("no pude guardar curiosity.json: %r", exc)

    # ── personalidad derivada ────────────────────────────────────────────
    def discoveries(self, n: int = 2) -> List[Dict[str, Any]]:
        return list(self._data.get("learned", []))[:n]

    def persona_hint(self) -> Tuple[List[str], str]:
        """Devuelve (temas que le interesan, opinión propia) para el prompt."""
        items = self.discoveries(2)
        topics = [it.get("short", "") for it in items if it.get("short")]
        opinion = items[0].get("opinion", "") if items else ""
        return topics[:2], opinion

    @staticmethod
    def _opinion_for(topic: str, score: float) -> str:
        core = _short_topic(topic)
        if score >= 0.3:
            return f"que no se habla lo suficiente de {core}"
        if score <= -0.3:
            return f"que hay que hablar de {core} sin miedo"
        return f"que nunca se sabe demasiado sobre {core}"

    # ── búsqueda ─────────────────────────────────────────────────────────
    def random_topic(self) -> str:
        seen = {_norm(x) for x in self._data.get("seen", [])}
        candidates = [t for t in SEED_TOPICS if _norm(t) not in seen]
        topic = random.choice(candidates or SEED_TOPICS)
        return topic

    async def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(headers=HEADERS, follow_redirects=True,
                                 timeout=httpx.Timeout(8.0, connect=5.0))

    async def _google(self, client: httpx.AsyncClient, query: str) -> List[Dict[str, str]]:
        if time.time() < self._google_ok_until:
            return []
        try:
            r = await client.get(
                "https://www.google.com/search",
                params={"q": query, "hl": "es", "num": "6", "gbv": "1"},
            )
            if r.status_code != 200 or "no se te redirecciona" in r.text:
                # Google sirve una página JS: no insistir durante 15 min.
                self._google_ok_until = time.time() + 900
                return []
            out: List[Dict[str, str]] = []
            for m in re.finditer(
                r'<a[^>]+href="(/url\?q=|https?://)([^"&]+)[^"]*"[^>]*>(.*?)</a>',
                r.text, flags=re.S,
            ):
                title = _plain(m.group(3))
                url = m.group(2)
                if not title or "google." in url or len(title) < 12:
                    continue
                if url.startswith("/url?q="):
                    url = url.split("/url?q=", 1)[1]
                out.append({"title": title, "url": url, "snippet": title,
                            "source": "Google"})
            return out[:6]
        except Exception as exc:  # noqa: BLE001
            logger.debug("Google falló: %r", exc)
            self._google_ok_until = time.time() + 900
            return []

    async def _google_cse(self, client: httpx.AsyncClient,
                          query: str) -> List[Dict[str, str]]:
        """Google Programmable Search (requiere clave + cx gratuitos)."""
        if not (self.google_key and self.google_cx):
            return []
        try:
            r = await client.get(
                "https://www.googleapis.com/customsearch/v1",
                params={"key": self.google_key, "cx": self.google_cx,
                        "q": query, "hl": "es", "num": "5"},
            )
            if r.status_code != 200:
                logger.debug("Google CSE %s: %s", r.status_code, r.text[:120])
                return []
            out = []
            for item in r.json().get("items", [])[:6]:
                out.append({
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                    "source": "Google",
                })
            return out
        except Exception as exc:  # noqa: BLE001
            logger.debug("Google CSE falló: %r", exc)
            return []

    async def _bing(self, client: httpx.AsyncClient, query: str) -> List[Dict[str, str]]:
        try:
            r = await client.get("https://www.bing.com/search",
                                 params={"q": query, "setlang": "es"})
            if r.status_code != 200:
                return []
            out: List[Dict[str, str]] = []
            for block in r.text.split('<li class="b_algo"')[1:]:
                block = block[:6000]
                m = re.search(r'<h2[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                              block, re.S)
                if not m:
                    continue
                snippet = ""
                for pat in (r'<p[^>]*>(.*?)</p>', r'<div class="b_caption[^"]*"[^>]*>(.*?)</div>'):
                    sm = re.search(pat, block, re.S)
                    if sm:
                        snippet = _plain(sm.group(1))
                        if len(snippet) > 30:
                            break
                title = _plain(m.group(2))
                out.append({"title": title, "url": m.group(1),
                            "snippet": snippet or title, "source": "Bing"})
                if len(out) >= 6:
                    break
            return out
        except Exception as exc:  # noqa: BLE001
            logger.debug("Bing falló: %r", exc)
            return []

    async def _wikipedia(self, client: httpx.AsyncClient, query: str) -> List[Dict[str, str]]:
        try:
            r = await client.get(
                "https://es.wikipedia.org/w/api.php",
                params={
                    "action": "query", "generator": "search", "gsrsearch": query,
                    "gsrlimit": "2", "prop": "extracts", "exintro": "1",
                    "explaintext": "1", "format": "json", "utf8": "1",
                },
            )
            pages = ((r.json().get("query") or {}).get("pages") or {})
            out: List[Dict[str, str]] = []
            for page in pages.values():
                extract = _WS_RE.sub(" ", page.get("extract") or "").strip()
                if not extract:
                    continue
                out.append({
                    "title": page.get("title", query),
                    "url": f"https://es.wikipedia.org/wiki/{page.get('title', '').replace(' ', '_')}",
                    "snippet": extract,
                    "source": "Wikipedia",
                })
            return out
        except Exception as exc:  # noqa: BLE001
            logger.debug("Wikipedia falló: %r", exc)
            return []

    async def search(self, query: str) -> List[Dict[str, str]]:
        async with await self._http() as client:
            results: List[Dict[str, str]] = []
            if self.engine in ("auto", "google"):
                results = await self._google_cse(client, query)
                if not results:
                    results = await self._google(client, query)
            if not results and self.engine in ("auto", "google", "bing"):
                results = await self._bing(client, query)
            if not results:
                results = await self._wikipedia(client, query)
            return results

    # ── aprendizaje ──────────────────────────────────────────────────────
    def _best_fact(self, results: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
        promo = re.compile(
            r"^(?:en este blog|en este art[ií]culo|en esta gu[ií]a|exploraremos|"
            r"te compartimos|descubre|haz clic|suscr[ií]bete|publicidad|compra)", re.I)

        def score(item: Dict[str, str]) -> tuple:
            snip = _clip_fact(item.get("snippet", ""))
            # Preferir datos reales, frases completas y longitud útil.
            return (not promo.match(snip),
                    snip.endswith((".", "!", "?")),
                    40 <= len(snip) <= 190,
                    len(snip))
        ranked = sorted(results, key=score, reverse=True)
        for item in ranked:
            snip = _clip_fact(item.get("snippet", ""))
            if len(snip) >= 40:
                item = dict(item)
                item["snippet"] = snip
                return item
        return ranked[0] if ranked else None

    @staticmethod
    def _score(text: str) -> float:
        words = re.findall(r"[a-záéíóúñ]+", _norm(text))
        pos = sum(1 for w in words if any(w.startswith(p) for p in POSITIVE))
        neg = sum(1 for w in words if any(w.startswith(n) for n in NEGATIVE))
        return (pos - neg) / max(1, pos + neg)

    async def learn(self, topic: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Busca un tema (o uno al azar), guarda el hallazgo y lo devuelve."""
        async with self._lock:
            query = (topic or "").strip() or self.random_topic()
            results = await self.search(query)
            best = self._best_fact(results)
            if not best:
                logger.info("Curiosidad: sin resultados para %r", query)
                return None

            fact = best["snippet"]
            key = hashlib.sha1(_norm(query + fact).encode()).hexdigest()[:16]
            score = self._score(f"{query} {fact}")
            record = {
                "key": key,
                "topic": query[:90],
                "short": _short_topic(query),
                "fact": fact,
                "source": best.get("source", "web"),
                "url": best.get("url", ""),
                "score": round(score, 2),
                "opinion": self._opinion_for(query, score),
                "ts": time.time(),
            }

            learned = [it for it in self._data.get("learned", [])
                       if it.get("key") != key and _norm(it.get("topic", "")) != _norm(query)]
            learned.insert(0, record)
            self._data["learned"] = learned[:MAX_LEARNED]
            seen = [s for s in self._data.get("seen", []) if _norm(s) != _norm(query)]
            seen.append(query)
            self._data["seen"] = seen[-400:]
            self._save()
            logger.info("🔎 Curiosidad aprendida (%s): %s", record["source"], query)
            return record

    # ── frases para el chat ──────────────────────────────────────────────
    @staticmethod
    def format_reply(record: Optional[Dict[str, Any]]) -> str:
        if not record:
            return ("Hoy no he encontrado nada que me convenza; la web estaba "
                    "esquiva. Prueba a pedírmelo otra vez en un rato.")
        openers = (
            "Acabo de cotillear sobre", "Estaba curioseando y me topé con",
            "He descubierto algo sobre", "Me crucé con un dato de",
        )
        topic = record.get("short") or record.get("topic", "algo random")
        fact = _clip_fact(record.get("fact", ""), 190)
        source = record.get("source", "la web")
        return f"{random.choice(openers)} {topic}: {fact} (vía {source})."

    def recall_reply(self, limit: int = 3) -> str:
        items = self.discoveries(limit)
        if not items:
            return ("Todavía no he curioseado nada. Dime «busca algo random» "
                    "y me pongo a ello.")
        lines = [
            f"{i + 1}) {it.get('short') or it.get('topic')}: {_clip_fact(it.get('fact', ''), 110)}"
            for i, it in enumerate(items)
        ]
        return "Lo último que aprendí: " + " ".join(lines)

    # ── intención desde el chat ──────────────────────────────────────────
    @staticmethod
    def interpret(text: str) -> Optional[Tuple[str, Optional[str]]]:
        raw = (text or "").strip()
        if not raw:
            return None
        if _RECALL_RE.search(raw):
            return ("recall", None)
        if not _VERB_RE.search(raw):
            return None
        if not (_EXPLICIT_RE.search(raw) or _RANDOM_RE.search(raw)):
            return None
        # "busca algo random" → tema al azar; "busca en google X" → tema X.
        m = _TOPIC_RE.search(raw)
        topic: Optional[str] = None
        if m:
            tail = m.group(1).strip(" .!?")
            low = _norm(tail)
            tail = re.sub(r"^(?:algo|una cosa|un tema|cosas)\s+(?:sobre|de)\s+",
                          "", tail, flags=re.I)
            if tail and not _RANDOM_RE.search(low) and low not in (
                "algo", "una cosa", "un tema", "cosas", "en google", "en internet",
                "un rato", "un poco", "ahora", "luego", "por favor",
            ):
                topic = tail[:90]
        return ("learn", topic)
