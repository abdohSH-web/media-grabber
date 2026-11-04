from PySide6.QtCore import QLocale, Qt

from .translations import TRANSLATIONS

# (code, the language's NAME IN ITS OWN LANGUAGE). These names are never translated.
LANGUAGES = (("en", "English"), ("ar", "العربية"))

_language = "en"


def default_language():
    """The first time, follow Windows: Arabic if the system language is Arabic."""
    return "ar" if QLocale.system().name().lower().startswith("ar") else "en"


def current_language():
    return _language


def tr(key, **values):
    """The text of `key` in the current language. {holes} are filled from `values`.
    A missing translation falls back to English, then to the key itself,
    so a forgotten text is visible but never crashes the app."""
    text = TRANSLATIONS[_language].get(key) or TRANSLATIONS["en"].get(key) or key
    return text.format(**values) if values else text


def apply_language(app, code):
    """Switch language AND direction (Arabic is written right to left)."""
    global _language
    _language = code if code in TRANSLATIONS else "en"
    direction = Qt.LayoutDirection.RightToLeft if _language == "ar" else Qt.LayoutDirection.LeftToRight
    app.setLayoutDirection(direction)      # Qt mirrors every layout, table and tab by itself