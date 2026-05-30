# app/ai/fuzzy.py
"""
FASE 2 — Utilidades de fuzzy matching.
Normalización de texto español, tolerancia a errores de escritura,
y búsqueda difusa de productos/clientes.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional, Sequence, Tuple


# ─────────────────────────────────────────────────────
# Normalización de texto
# ─────────────────────────────────────────────────────

def strip_accents(text: str) -> str:
    """Elimina acentos/diacríticos preservando ñ."""
    if not text:
        return ""
    out = []
    for ch in unicodedata.normalize("NFD", text):
        cat = unicodedata.category(ch)
        # Preservar ñ (combina n + ̃ )
        if cat == "Mn":  # Mark, Nonspacing
            # Preservar la tilde de ñ (U+0303)
            if ch == "\u0303" and out and out[-1].lower() == "n":
                out.append(ch)
                continue
            # Descartar los demás acentos
            continue
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def normalize_text(text: str) -> str:
    """
    Normalización completa:
    - minúsculas
    - strip accents (excepto ñ)
    - colapsar espacios
    - quitar signos interrogación/exclamación
    """
    t = (text or "").strip().lower()
    t = strip_accents(t)
    t = re.sub(r"[¿¡?!.,;:\"'()]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _tokenize(text: str) -> list[str]:
    """Tokeniza texto normalizado."""
    return [w for w in normalize_text(text).split() if len(w) >= 2]


# ─────────────────────────────────────────────────────
# Distancia y similitud
# ─────────────────────────────────────────────────────

def _levenshtein(a: str, b: str) -> int:
    """Distancia de Levenshtein optimizada para strings cortos."""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if len(b) == 0:
        return len(a)

    prev_row = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr_row = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr_row.append(min(
                curr_row[j] + 1,        # inserción
                prev_row[j + 1] + 1,    # eliminación
                prev_row[j] + cost,      # sustitución
            ))
        prev_row = curr_row
    return prev_row[-1]


def char_similarity(a: str, b: str) -> float:
    """Similitud basada en Levenshtein normalizada (0.0 - 1.0)."""
    a_norm = normalize_text(a)
    b_norm = normalize_text(b)
    if not a_norm or not b_norm:
        return 0.0
    if a_norm == b_norm:
        return 1.0
    max_len = max(len(a_norm), len(b_norm))
    dist = _levenshtein(a_norm, b_norm)
    return max(0.0, 1.0 - dist / max_len)


def token_similarity(a: str, b: str) -> float:
    """
    Similitud basada en tokens compartidos (0.0 - 1.0).
    Buena para comparar nombres de productos multi-palabra.
    """
    tokens_a = set(_tokenize(a))
    tokens_b = set(_tokenize(b))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)  # Jaccard


def combined_similarity(query: str, candidate: str) -> float:
    """
    Score combinado: 60% char similarity + 40% token overlap.
    Balanceo pensado para un POS donde:
    - La gente escribe parcial ("sold" para "soldadura")
    - A veces con typos ("soldadra", "silikon")
    """
    # Caso especial: substring directo
    q = normalize_text(query)
    c = normalize_text(candidate)
    if q in c or c in q:
        longer = max(len(q), len(c))
        shorter = min(len(q), len(c))
        return 0.7 + 0.3 * (shorter / longer) if longer > 0 else 1.0

    char_sim = char_similarity(query, candidate)
    tok_sim = token_similarity(query, candidate)
    return 0.6 * char_sim + 0.4 * tok_sim


# ─────────────────────────────────────────────────────
# Fuzzy matching contra listas
# ─────────────────────────────────────────────────────

def fuzzy_match_best(
    query: str,
    candidates: Sequence[str],
    threshold: float = 0.45,
) -> Optional[Tuple[str, float]]:
    """
    Encuentra el mejor match en una lista de candidatos.
    Retorna (best_candidate, score) o None si ninguno supera el threshold.
    """
    if not query or not candidates:
        return None

    best: Optional[Tuple[str, float]] = None
    for cand in candidates:
        score = combined_similarity(query, cand)
        if score >= threshold:
            if best is None or score > best[1]:
                best = (cand, score)
    return best


def fuzzy_match_top(
    query: str,
    candidates: Sequence[str],
    threshold: float = 0.35,
    limit: int = 5,
) -> list[Tuple[str, float]]:
    """
    Retorna los top N candidatos que superan el threshold,
    ordenados por score desc.
    """
    if not query or not candidates:
        return []

    scored = []
    for cand in candidates:
        score = combined_similarity(query, cand)
        if score >= threshold:
            scored.append((cand, score))

    scored.sort(key=lambda x: -x[1])
    return scored[:limit]


# ─────────────────────────────────────────────────────
# Fuzzy matching para keywords de dominio/intención
# ─────────────────────────────────────────────────────

# Correcciones comunes de typos en español para POS
_COMMON_TYPOS: dict[str, str] = {
    # Ventas
    "benta": "venta", "bentas": "ventas", "vendi": "vendí",
    "bendi": "vendí", "bendí": "vendí", "bentdi": "vendí",
    # Gastos
    "gatos": "gastos", "gsto": "gasto", "gastp": "gasto",
    # Caja
    "cja": "caja", "caha": "caja", "cjaa": "caja",
    # Inventario
    "imventario": "inventario", "invetario": "inventario",
    "imbentario": "inventario", "inbentario": "inventario",
    # Stock
    "stok": "stock", "estok": "stock", "estoc": "stock", "sotck": "stock",
    # Productos
    "prodcutos": "productos", "prductos": "productos",
    "prducto": "producto", "porducto": "producto",
    # Clientes
    "cleintes": "clientes", "clente": "cliente",
    "cliete": "cliente", "cleinte": "cliente",
    # Proveedores
    "proveedor": "proveedor", "probedor": "proveedor",
    "probeedores": "proveedores", "proveedore": "proveedores",
    # Acciones
    "cofirmar": "confirmar", "confimar": "confirmar",
    "confrimr": "confirmar", "confimrar": "confirmar",
    "agnregar": "agregar", "agegar": "agregar", "agreagr": "agregar",
    "bsucar": "buscar", "busacr": "buscar", "buscra": "buscar",
    "elimnar": "eliminar", "elimar": "eliminar",
    # Sinpe
    "sinpee": "sinpe", "simpe": "sinpe", "snipe": "sinpe",
    # Efectivo
    "efetivo": "efectivo", "efectio": "efectivo", "efecitvo": "efectivo",
    # Tarjeta
    "tarjea": "tarjeta", "tarjet": "tarjeta", "tajeta": "tarjeta",
    # Financiero
    "ganacia": "ganancia", "ganansia": "ganancia",
    "utiliad": "utilidad", "utildad": "utilidad",
    "rentabiliad": "rentabilidad",
    # Crédito
    "credito": "crédito", "cretido": "crédito",
    # Factura
    "facrura": "factura", "factuta": "factura", "factra": "factura",
    # Descuento
    "descento": "descuento", "dscuento": "descuento",
    "desceunto": "descuento",
}


def fix_typos(text: str) -> str:
    """
    Corrige typos conocidos en el texto.
    Opera palabra por palabra para no romper frases.
    """
    words = text.split()
    result = []
    for w in words:
        w_lower = w.lower()
        w_clean = normalize_text(w)
        # Primero: tabla de typos directos
        if w_clean in _COMMON_TYPOS:
            result.append(_COMMON_TYPOS[w_clean])
        elif w_lower in _COMMON_TYPOS:
            result.append(_COMMON_TYPOS[w_lower])
        else:
            result.append(w)
    return " ".join(result)


def keyword_in_text(keyword: str, text: str, threshold: float = 0.78) -> bool:
    """
    Verifica si un keyword aparece en el texto, con tolerancia fuzzy.
    Busca el keyword como token completo o como parte de un token.

    threshold=0.78 permite ~1 error en palabras de 5+ chars.
    """
    kw = normalize_text(keyword)
    tokens = _tokenize(text)

    for tok in tokens:
        if tok == kw:
            return True
        if len(kw) >= 3 and len(tok) >= 3:
            if char_similarity(kw, tok) >= threshold:
                return True
    return False


def any_keyword_in_text(keywords: Sequence[str], text: str, threshold: float = 0.78) -> bool:
    """True si ALGUNO de los keywords está en el texto (fuzzy)."""
    for kw in keywords:
        if keyword_in_text(kw, text, threshold):
            return True
    return False