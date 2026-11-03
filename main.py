import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from grabber.tools import use_bundled_tools
from ui.main_window import MainWindow
from ui.paths import resource_path
from ui.theme import apply_theme


def data_folder():
    """Our folder inside AppData (it holds the history, the queue and the log)."""
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return Path(location)


def redirect_output_to_log():
    """The packaged app has no terminal, and sys.stdout / sys.stderr can even be None,
    which makes print() and tracebacks crash. So we send everything to a log file."""
    if not getattr(sys, "frozen", False):
        return                              # running from source: keep the normal terminal
    folder = data_folder()
    folder.mkdir(parents=True, exist_ok=True)
    log = open(folder / "app.log", "a", encoding="utf-8", buffering=1)   # 1 = line by line
    print(f"--- Media Grabber started {datetime.now():%Y-%m-%d %H:%M:%S} ---", file=log)
    sys.stdout = log
    sys.stderr = log


def main():
    app = QApplication(sys.argv)     # one per program: owns the event loop
    # These names decide where Qt stores our files (history, log...) on Windows
    app.setOrganizationName("MediaGrabber")
    app.setApplicationName("MediaGrabber")

    redirect_output_to_log()         # after the names: they decide the folder
    use_bundled_tools()              # BEFORE the window: it looks for FFmpeg when it starts

    # The theme the user chose last time (dark by default)
    settings = QSettings("MediaGrabber", "MediaGrabber")
    apply_theme(app, settings.value("ui/theme", "dark"))

    # The icon is optional: if the file isn't there, the app uses the default one
    icon_file = resource_path("assets/icon.png")
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())             # starts the loop: the window now reacts to clicks


if __name__ == "__main__":
    main()