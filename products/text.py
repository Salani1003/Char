"""
Normalización y comparación de nombres de los catálogos (marca, modelo,
categoría, color), para que "Nike", "nike" y "NIKE" sean la misma marca.
"""
import unicodedata

__all__ = ['fold_text', 'normalize_name', 'STYLE_WORDS', 'STYLE_SENTENCE', 'STYLE_UPPER', 'STYLE_CAPITALIZE']

STYLE_WORDS = 'words'
STYLE_SENTENCE = 'sentence'
STYLE_UPPER = 'upper'
STYLE_CAPITALIZE = 'capitalize'


def fold_text(text: str) -> str:
    """Forma comparable de un texto: sin tildes, sin mayúsculas y con espacios colapsados."""
    stripped = ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
    return ' '.join(stripped.casefold().split())


def normalize_name(name: str, style: str = STYLE_SENTENCE) -> str:
    """
    Normaliza un nombre para guardarlo: colapsa los espacios y, si llegó TODO
    en minúsculas ("nike", "azul marino"), lo capitaliza: cada palabra con
    `STYLE_WORDS` ("Nike", "Marca X"), sólo la primera letra con
    `STYLE_SENTENCE` ("Azul marino"). Si ya trae alguna mayúscula ("NIKE",
    "KitchenAid", "MarketPlace") se respeta como viene: capitalizar a ciegas
    rompería grafías propias. `STYLE_UPPER` (talles: "xs" -> "XS") pasa todo a
    mayúsculas siempre. No usa `str.title()`, que rompe apóstrofes.
    """
    words = name.split()
    if style == STYLE_CAPITALIZE:
        # Siempre: "ROJO" / "rojo" -> "Rojo"; "AZUL MARINO" -> "Azul marino".
        joined = ' '.join(words).lower()
        return joined[:1].upper() + joined[1:]
    if style == STYLE_UPPER:
        return ' '.join(words).upper()
    if name == name.lower():
        if style == STYLE_WORDS:
            words = [w[:1].upper() + w[1:] for w in words]
        elif words:
            words[0] = words[0][:1].upper() + words[0][1:]
    return ' '.join(words)
