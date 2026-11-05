from .translations import TRANSLATIONS

# (code, the language's NAME IN ITS OWN LANGUAGE). These names are never translated.
LANGUAGES = (("en", "English"), ("ar", "العربية"))

_language = "en"


def default_language():
    """The first time, follow Windows: Arabic if the system language is Arabic."""
    from PySide6.QtCore import QLocale          # imported here so the rest works without Qt
    return "ar" if QLocale.system().name().lower().startswith("ar") else "en"


def current_language():
    return _language


def set_language(code):
    global _language
    _language = code if code in TRANSLATIONS else "en"


def tr(key, **values):
    """The text of `key` in the current language. {holes} are filled from `values`.
    A missing translation falls back to English, then to the key itself,
    so a forgotten text is visible but never crashes the app."""
    text = TRANSLATIONS[_language].get(key) or TRANSLATIONS["en"].get(key) or key
    return text.format(**values) if values else text


def error_text(error):
    """An exception as text for the user: translated when it carries a known code,
    otherwise its plain message."""
    code = getattr(error, "code", None)
    key = f"err_{code}"
    if code and key in TRANSLATIONS["en"]:
        try:
            return tr(key, **error.details)
        except KeyError:                         # a {hole} we have no value for
            pass
    return str(error)


def apply_language(app, code):
    """Switch language AND direction (Arabic is written right to left)."""
    from PySide6.QtCore import Qt
    set_language(code)
    direction = Qt.LayoutDirection.RightToLeft if _language == "ar" else Qt.LayoutDirection.LeftToRight
    app.setLayoutDirection(direction)           # Qt mirrors every layout, table and tab by itself