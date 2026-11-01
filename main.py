import sys

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)     # one per program: owns the event loop
    # These names decide where Qt stores our files (like the history) on Windows
    app.setOrganizationName("MediaGrabber")
    app.setApplicationName("MediaGrabber")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())             # starts the loop: the window now reacts to clicks


if __name__ == "__main__":
    main()