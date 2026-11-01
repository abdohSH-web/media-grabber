import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.paths import resource_path
from ui.theme import apply_theme


def main():
    app = QApplication(sys.argv)     # one per program: owns the event loop
    # These names decide where Qt stores our files (like the history) on Windows
    app.setOrganizationName("MediaGrabber")
    app.setApplicationName("MediaGrabber")

    apply_theme(app)

    # The icon is optional: if the file isn't there, the app simply uses the default one
    icon_file = resource_path("assets/icon.png")
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())             # starts the loop: the window now reacts to clicks


if __name__ == "__main__":
    main()