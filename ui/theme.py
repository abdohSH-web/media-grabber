from pathlib import Path
from string import Template

from PySide6.QtCore import QStandardPaths

# One place for ALL the colours. Change a value here and the whole app follows.
THEMES = {
    "dark": {
        "background": "#1e1f22",
        "surface": "#2b2d31",
        "surface_light": "#383a40",
        "border": "#44464d",
        "border_strong": "#6b6f78",
        "text": "#e6e6e6",
        "text_muted": "#9a9da3",
        "accent": "#5b8def",
        "accent_hover": "#7aa2f7",
        "warning": "#f0b429",
    },
    "light": {
        "background": "#f4f5f7",
        "surface": "#ffffff",
        "surface_light": "#e9ebef",
        "border": "#cdd1d8",
        "border_strong": "#9aa0aa",
        "text": "#1f2328",
        "text_muted": "#6b7280",
        "accent": "#2f6fed",
        "accent_hover": "#1f5bd4",
        "warning": "#b45309",
    },
}

_current = "dark"          # the theme in use (the clip slider reads its colours from here)

# A tick mark as a tiny picture. {color} and {opacity} are filled in below.
_CHECK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 14 14" width="14" height="14">'
    '<path d="M3 7.5 L6 10.5 L11 4" fill="none" stroke="{color}" stroke-opacity="{opacity}" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)

# $name placeholders are replaced by the values of the chosen theme
_QSS = Template("""
QWidget { background-color: $background; color: $text; font-size: 13px; }
QLabel { background: transparent; }
QLabel#muted { color: $text_muted; }
QLabel#warning { color: $warning; }
QLabel#title { font-size: 16px; font-weight: bold; }
QLabel#thumbnail {
    background-color: $surface; color: $text_muted;
    border: 1px solid $border; border-radius: 6px;
}
QToolTip { background-color: $surface_light; color: $text; border: 1px solid $border; padding: 4px; }
QStatusBar { border-top: 1px solid $border; }
QStatusBar QLabel { color: $text_muted; }

QLineEdit, QComboBox, QSpinBox {
    background-color: $surface; border: 1px solid $border;
    border-radius: 6px; padding: 6px 8px; selection-background-color: $accent;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid $accent; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: $text_muted; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background-color: $surface; border: 1px solid $border; selection-background-color: $accent;
}

QPushButton {
    background-color: $surface_light; border: 1px solid $border;
    border-radius: 6px; padding: 7px 14px;
}
QPushButton:hover { background-color: $border; }
QPushButton:pressed { background-color: $surface; }
QPushButton:disabled { color: $text_muted; background-color: $surface; }
QPushButton#primary { background-color: $accent; border: none; color: white; font-weight: bold; }
QPushButton#primary:hover { background-color: $accent_hover; }
QPushButton#primary:disabled { background-color: $surface_light; color: $text_muted; }

QProgressBar {
    background-color: $surface; border: 1px solid $border;
    border-radius: 6px; text-align: center;
}
QProgressBar::chunk { background-color: $accent; border-radius: 5px; }

QTabWidget::pane { border: 1px solid $border; border-radius: 6px; }
QTabBar::tab {
    background: $surface; padding: 8px 20px; margin-right: 2px;
    border: 1px solid $border; border-bottom: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
}
QTabBar::tab:selected { background: $surface_light; font-weight: bold; }

QGroupBox {
    border: 1px solid $border; border-radius: 6px;
    margin-top: 14px; padding: 14px 10px 10px 10px;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }

QTableWidget {
    background-color: $surface; border: 1px solid $border; border-radius: 6px;
    gridline-color: $border; selection-background-color: $accent; selection-color: white;
}
QHeaderView::section {
    background-color: $surface_light; color: $text; padding: 6px;
    border: none; border-right: 1px solid $border;
}

QListWidget { background-color: $surface; border: 1px solid $border; border-radius: 6px; }
QListWidget::item { padding: 4px; }
QListWidget::item:selected { background-color: $accent; color: white; }

/* ---------- Options: round, obvious, blue when chosen ---------- */
QCheckBox, QRadioButton { spacing: 8px; background: transparent; }

QCheckBox::indicator, QRadioButton::indicator, QListWidget::indicator {
    width: 14px; height: 14px; border-radius: 9px;
    border: 2px solid $border_strong; background-color: $surface;
}
QCheckBox::indicator, QListWidget::indicator { $check_faint_rule }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: $accent; }

QCheckBox::indicator:checked, QListWidget::indicator:checked {
    background-color: $accent; border-color: $accent; $check_white_rule
}
QRadioButton::indicator:checked {
    border-color: $accent;
    background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 $accent, stop:0.5 $accent, stop:0.55 $surface, stop:1 $surface);
}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled { border-color: $border; }
QCheckBox::indicator:checked:disabled { background-color: $border; border-color: $border; }

QScrollBar:vertical { background: $surface; width: 12px; margin: 0; }
QScrollBar::handle:vertical { background: $border; border-radius: 6px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: $surface; height: 12px; margin: 0; }
QScrollBar::handle:horizontal { background: $border; border-radius: 6px; min-width: 24px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
""")


def current_colors():
    """The colours of the theme in use."""
    return THEMES[_current]


def _write_icons(colors):
    """The tick marks are tiny SVG files in a folder in AppData (their colour depends
    on the theme). Returns {name: path}, or {} if they can't be written: the options
    are then just plain blue circles without the tick."""
    try:
        location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        folder = Path(location) / "icons"
        folder.mkdir(parents=True, exist_ok=True)
        pictures = {
            "check_white": _CHECK_SVG.format(color="#ffffff", opacity=1),
            "check_faint": _CHECK_SVG.format(color=colors["text_muted"], opacity=0.55),
        }
        paths = {}
        for name, svg in pictures.items():
            path = folder / f"{name}.svg"
            path.write_text(svg, encoding="utf-8")
            paths[name] = path.as_posix()          # forward slashes: what url() expects
        return paths
    except OSError:
        return {}


def apply_theme(app, name="dark"):
    """Apply a theme. Safe to call again while the app is running: it switches live."""
    global _current
    _current = name if name in THEMES else "dark"
    colors = THEMES[_current]

    icons = _write_icons(colors)
    rules = {
        "check_faint_rule": f'image: url("{icons["check_faint"]}");' if "check_faint" in icons else "",
        "check_white_rule": f'image: url("{icons["check_white"]}");' if "check_white" in icons else "",
    }

    app.setStyle("Fusion")             # a consistent base look on every Windows version
    app.setStyleSheet(_QSS.substitute({**colors, **rules}))