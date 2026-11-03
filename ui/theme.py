from string import Template

# One place for ALL the colours. Change a value here and the whole app follows.
THEMES = {
    "dark": {
        "background": "#1e1f22",
        "surface": "#2b2d31",
        "surface_light": "#383a40",
        "border": "#44464d",
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
        "text": "#1f2328",
        "text_muted": "#6b7280",
        "accent": "#2f6fed",
        "accent_hover": "#1f5bd4",
        "warning": "#b45309",
    },
}

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

QCheckBox, QRadioButton { spacing: 8px; background: transparent; }

QScrollBar:vertical { background: $surface; width: 12px; margin: 0; }
QScrollBar::handle:vertical { background: $border; border-radius: 6px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: $surface; height: 12px; margin: 0; }
QScrollBar::handle:horizontal { background: $border; border-radius: 6px; min-width: 24px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
""")


def apply_theme(app, name="dark"):
    """Apply a theme. Safe to call again while the app is running: it switches live."""
    colors = THEMES.get(name, THEMES["dark"])
    app.setStyle("Fusion")             # a consistent base look on every Windows version
    app.setStyleSheet(_QSS.substitute(colors))