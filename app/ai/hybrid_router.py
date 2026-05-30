# app/ai/hybrid_router.py
"""
FASE 6 — Router híbrido.
Decide si una consulta va por el camino rápido (clasificador local)
o por el LLM con function calling.

Criterios para usar LLM:
  1. El clasificador tiene baja confianza (< threshold)
  2. La consulta es compleja (multi-intención, preguntas abiertas)
  3. La consulta no matchea ningún patrón del clasificador
  4. El usuario hace preguntas de dominio general (no hay tool)
  5. Texto largo con contexto conversacional

Criterios para camino rápido:
  1. Alta confianza del clasificador
  2. Intención clara y conocida (vender, buscar, navegar, consultar dato)
  3. Estados pendientes (confirm_sale, choose_product, etc.)
  4. Comandos cortos y directos
"""
from __future__ import annotations

import re

from app.ai.classifier import classify, ClassificationResult
from app.ai.llm_engine import is_llm_available
from app.ai.fuzzy import normalize_text


# ─────────────────────────────────────────────────────
# Umbrales de decisión
# ─────────────────────────────────────────────────────

# Si el clasificador supera este umbral → camino rápido
CONFIDENCE_THRESHOLD = 0.55

# Palabras clave que SIEMPRE van por camino rápido (operaciones de carrito)
_ALWAYS_FAST_PATTERNS = re.compile(
    r"\b("
    r"vende|vend[eé]|vender|busca|buscar|b[uú]scame|"
    r"agrega|agreg[aá]|agregar|quita|quit[aá]|"
    r"confirmar|confirm[aá]|cobrar|cobr[aá]|"
    r"cancelar|cancel[aá]|deshacer|undo|"
    r"s[ií]|no|dale|ok|okay|"
    r"\d+\s*$"  # solo un número (selección de opción)
    r")\b",
    re.I,
)

# Señales de complejidad que sugieren LLM
_COMPLEXITY_SIGNALS = [
    # Preguntas abiertas / consultivas
    r"\b(por\s*qu[eé]|c[oó]mo\s+puedo|qu[eé]\s+me\s+recomiend|qu[eé]\s+deber[ií]a|conviene|mejor\s+opci[oó]n)\b",
    # Comparaciones
    r"\b(compar[aá]|vs|versus|diferencia\s+entre|mejor\s+que)\b",
    # Análisis / interpretación
    r"\b(anali[zs][aá]|interpret[aá]|explic[aá]|por\s*qu[eé]\s+(baj|sub)|tendencia|patr[oó]n)\b",
    # Multi-paso
    r"\b(primero.*luego|despu[eé]s|tambi[eé]n.*y\s+adem[aá]s)\b",
    # Preguntas generales de negocio
    r"\b(consejo|sugerencia|estrategia|mejorar|optimizar)\b",
]


# ─────────────────────────────────────────────────────
# Tipos de resultado del router
# ─────────────────────────────────────────────────────

class RouteDecision:
    FAST = "fast"       # Camino rápido (clasificador)
    LLM = "llm"         # Camino LLM
    FALLBACK = "fallback"  # Sin LLM disponible, usar fallback

    def __init__(self, path: str, reason: str = "", classification: ClassificationResult = None):
        self.path = path
        self.reason = reason
        self.classification = classification

    @property
    def is_fast(self) -> bool:
        return self.path == self.FAST

    @property
    def is_llm(self) -> bool:
        return self.path == self.LLM


# ─────────────────────────────────────────────────────
# Función principal del router
# ─────────────────────────────────────────────────────

def route(text_raw: str, has_pending_state: bool = False) -> RouteDecision:
    """
    Decide si una consulta va por fast path o LLM.

    Args:
        text_raw: texto del usuario
        has_pending_state: True si hay un estado pendiente (confirm_sale, choose_product, etc.)

    Returns:
        RouteDecision con .path = "fast" | "llm" | "fallback"
    """
    text = normalize_text(text_raw)

    # ── Regla 1: Estados pendientes SIEMPRE van rápido ──
    if has_pending_state:
        return RouteDecision(RouteDecision.FAST, reason="pending_state")

    # ── Regla 2: Comandos de carrito SIEMPRE van rápido ──
    if _ALWAYS_FAST_PATTERNS.search(text):
        return RouteDecision(RouteDecision.FAST, reason="cart_command")

    # ── Regla 3: Texto muy corto (1-2 palabras) → rápido ──
    word_count = len(text.split())
    if word_count <= 2:
        return RouteDecision(RouteDecision.FAST, reason="short_text")

    # ── Regla 4: Clasificar ──
    cls = classify(text_raw)

    # Alta confianza → rápido
    if cls.confidence >= CONFIDENCE_THRESHOLD:
        return RouteDecision(RouteDecision.FAST, reason=f"high_confidence({cls.confidence:.2f})", classification=cls)

    # Dominio conocido con intención clara → rápido
    if cls.domain != "unknown" and cls.intent != "unknown":
        return RouteDecision(RouteDecision.FAST, reason=f"known_domain({cls.domain}/{cls.intent})", classification=cls)

    # ── Regla 5: Señales de complejidad → LLM ──
    for pattern in _COMPLEXITY_SIGNALS:
        if re.search(pattern, text, re.I):
            if is_llm_available():
                return RouteDecision(RouteDecision.LLM, reason="complexity_signal", classification=cls)
            return RouteDecision(RouteDecision.FALLBACK, reason="complexity_no_llm", classification=cls)

    # ── Regla 6: Dominio desconocido → LLM si disponible ──
    if cls.domain == "unknown":
        if is_llm_available():
            return RouteDecision(RouteDecision.LLM, reason="unknown_domain", classification=cls)
        return RouteDecision(RouteDecision.FALLBACK, reason="unknown_no_llm", classification=cls)

    # ── Regla 7: Texto largo con baja confianza → LLM ──
    if word_count > 8 and cls.confidence < CONFIDENCE_THRESHOLD:
        if is_llm_available():
            return RouteDecision(RouteDecision.LLM, reason="long_low_confidence", classification=cls)

    # ── Default: camino rápido ──
    return RouteDecision(RouteDecision.FAST, reason="default", classification=cls)