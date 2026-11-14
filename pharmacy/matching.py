"""Deterministic safety net for matching invoice product names to the stock catalog.

The AI usually maps "OMEPRAZOLE 20MG GASTRO-RES CAP 14" to "Omeprazole 20mg caps (14)", but not
every time. When it answers NONE (or a match whose medicine name isn't on the line), this code
matches by medicine name + strength, and only when exactly one catalog item fits.
"""
import re

STRENGTH = re.compile(r"(\d[\d,\.]*)\s*(mg|mcg|iu|g|ml)\b")
STOP = {"tabs", "tab", "caps", "cap", "capsules", "tablets", "inhaler", "mg", "mcg", "iu", "ml", "softgel"}


def _norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"(?<=\d),(?=\d{3})", "", s)  # 50,000 -> 50000
    return s


def _strengths(s: str) -> set:
    return {(m.group(1).rstrip("."), m.group(2)) for m in STRENGTH.finditer(_norm(s))}


def _words(s: str) -> list:
    return [w for w in re.findall(r"[a-z]{3,}", _norm(s)) if w not in STOP]


def _word_hits(cat_words, line_words) -> int:
    hits = 0
    for cw in cat_words:
        if any(lw.startswith(cw) or cw.startswith(lw) for lw in line_words if len(lw) >= 3):
            hits += 1
    return hits


def _fits(catalog_name: str, product: str) -> int:
    """0 = doesn't fit. Otherwise a score: the medicine name and strength must both match."""
    cat_words, line_words = _words(catalog_name), _words(product)
    if not cat_words or not _word_hits(cat_words[:1], line_words):  # first word = the medicine
        return 0
    cs, ls = _strengths(catalog_name), _strengths(product)
    if cs and not (cs & ls):
        return 0
    return 10 + _word_hits(cat_words, line_words)


def best_match(product: str, catalog_names) -> str | None:
    scored = sorted(((_fits(c, product), c) for c in catalog_names), reverse=True)
    if not scored or scored[0][0] == 0:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None  # ambiguous: leave it for a human
    return scored[0][1]


def fill_matches(invoice: dict, catalog_names) -> dict:
    """Fix missing or implausible catalog matches in place. Returns the invoice."""
    catalog_names = list(catalog_names)
    for line in invoice.get("lines", []):
        product = line.get("product_name", "")
        current = line.get("catalog_match", "NONE")
        plausible = current in catalog_names and _fits(current, product) > 0
        if not plausible:
            found = best_match(product, catalog_names)
            if found:
                line["catalog_match"] = found
            elif current not in catalog_names:
                line["catalog_match"] = "NONE"
    return invoice
