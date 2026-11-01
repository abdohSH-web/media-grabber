import threading
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThreadPool, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from grabber.downloader import Downloader
from grabber.models import CookieSettings, DownloadRequest, Mode

from .formatting import format_duration, format_eta, format_speed
from .workers import Worker, load_thumbnail

# Quality choices offered for playlists (each video has its own list of heights)
PRESET_HEIGHTS = (1080, 720, 480, 360)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Media Grabber")
        self.resize(680, 580)

        self.downloader = Downloader()
        self.pool = QThreadPool.globalInstance()   # Qt's ready-made thread pool

        self.info = None              # MediaInfo of the last fetched link (None = nothing ready)
        self.last_folder = None
        self.fetch_worker = None      # we keep references so Python doesn't delete them
        self.download_worker = None
        self.cancel_event = None      # a threading.Event shared with the download thread

        # QSettings remembers small settings between runs (on Windows: in the registry)
        self.settings = QSettings("MediaGrabber", "MediaGrabber")
        self.cookie_file = None       # path of the chosen cookies.txt, if any

        self.build_ui()
        self.load_cookie_settings()

    # ============================================================
    # Building the window
    # ============================================================
    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)          # stacks things top to bottom
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # --- Row 1: the link + Fetch button ---
        link_row = QHBoxLayout()               # places things side by side
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Paste a link here...")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.returnPressed.connect(self.on_fetch_clicked)   # Enter key
        self.fetch_button = QPushButton("Fetch")
        self.fetch_button.clicked.connect(self.on_fetch_clicked)
        link_row.addWidget(self.url_edit, stretch=1)    # stretch=1: takes the free space
        link_row.addWidget(self.fetch_button)
        layout.addLayout(link_row)

        self.playlist_check = QCheckBox("If the link belongs to a playlist, use the whole playlist")
        layout.addWidget(self.playlist_check)

        # --- Row 2: the info card (thumbnail + text) ---
        card = QHBoxLayout()
        self.thumbnail_label = QLabel("No preview")
        self.thumbnail_label.setFixedSize(240, 135)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet("background: #2b2b2b; color: #999;")

        text_column = QVBoxLayout()
        self.title_label = QLabel("Paste a link and press Fetch")
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.meta_label = QLabel("")
        text_column.addWidget(self.title_label)
        text_column.addWidget(self.meta_label)
        text_column.addStretch()

        card.addWidget(self.thumbnail_label)
        card.addLayout(text_column, stretch=1)
        layout.addLayout(card)

        # --- Row 3: options ---
        options_row = QHBoxLayout()
        self.video_radio = QRadioButton("Video")
        self.audio_radio = QRadioButton("Audio (MP3)")
        self.video_radio.setChecked(True)
        self.video_radio.toggled.connect(self.update_options)
        self.quality_box = QComboBox()
        self.quality_box.addItem("Best available", None)   # (text, hidden value)
        options_row.addWidget(self.video_radio)
        options_row.addWidget(self.audio_radio)
        options_row.addWidget(QLabel("Quality:"))
        options_row.addWidget(self.quality_box, stretch=1)
        layout.addLayout(options_row)

        # --- Row 4: where to save ---
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(str(Path.home() / "Downloads"))
        self.folder_edit.setReadOnly(True)
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self.choose_folder)
        folder_row.addWidget(QLabel("Save to:"))
        folder_row.addWidget(self.folder_edit, stretch=1)
        folder_row.addWidget(browse_button)
        layout.addLayout(folder_row)

        # --- Row 4b: cookies (needed when YouTube asks you to prove you're not a bot) ---
        cookies_row = QHBoxLayout()
        self.cookie_box = QComboBox()
        self.cookie_box.setToolTip(
            "YouTube sometimes asks you to prove you're not a bot.\n"
            "A cookies.txt file (or Firefox) fixes it.\n"
            "Chrome/Edge/Brave are usually blocked on Windows."
        )
        self.cookie_box.addItem("No cookies", None)
        self.cookie_box.addItem("Firefox", "firefox")
        self.cookie_box.addItem("Edge (often blocked)", "edge")
        self.cookie_box.addItem("Chrome (often blocked)", "chrome")
        self.cookie_box.addItem("Brave (often blocked)", "brave")
        self.cookie_box.addItem("cookies.txt file...", "file")
        self.cookie_box.currentIndexChanged.connect(self.on_cookie_choice_changed)
        self.cookie_file_label = QLabel("")
        cookies_row.addWidget(QLabel("Cookies:"))
        cookies_row.addWidget(self.cookie_box)
        cookies_row.addWidget(self.cookie_file_label, stretch=1)
        layout.addLayout(cookies_row)

        # --- Row 5: action buttons ---
        buttons_row = QHBoxLayout()
        self.download_button = QPushButton("Download")
        self.download_button.setEnabled(False)          # nothing to download yet
        self.download_button.clicked.connect(self.on_download_clicked)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)            # only while a download runs
        self.cancel_button.clicked.connect(self.on_cancel_clicked)
        self.open_button = QPushButton("Open folder")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_folder)
        buttons_row.addWidget(self.download_button, stretch=1)
        buttons_row.addWidget(self.cancel_button)
        buttons_row.addWidget(self.open_button)
        layout.addLayout(buttons_row)

        # --- Row 6: progress + status ---
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label = QLabel("Ready")
        layout.addWidget(self.progress)
        layout.addWidget(self.status_label)
        layout.addStretch()

    # ============================================================
    # Small helpers
    # ============================================================
    def set_busy(self, busy, message):
        """Lock or unlock the buttons, and show a status message."""
        self.fetch_button.setEnabled(not busy)
        self.download_button.setEnabled(not busy and self.info is not None)
        self.status_label.setText(message)

    def reset_progress(self):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

    def update_options(self, *_):
        # Quality only makes sense for video
        self.quality_box.setEnabled(self.video_radio.isChecked())

    def fill_qualities(self, heights):
        self.quality_box.clear()
        self.quality_box.addItem("Best available", None)
        for height in heights:
            # The hidden value is a NUMBER: it becomes DownloadRequest.max_height
            self.quality_box.addItem(f"Up to {height}p", height)

    def show_thumbnail(self, data):
        pixmap = QPixmap()
        if data and pixmap.loadFromData(data):
            self.thumbnail_label.setPixmap(pixmap.scaled(
                self.thumbnail_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            self.thumbnail_label.setPixmap(QPixmap())    # clears the old image
            self.thumbnail_label.setText("No preview")

    @staticmethod
    def describe(info):
        parts = [info.uploader]
        if info.duration_seconds:
            parts.append(format_duration(info.duration_seconds))
        if info.is_playlist:
            parts.append(f"{info.entry_count} items")
        return "  •  ".join(parts)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder", self.folder_edit.text())
        if folder:                                       # empty string = user cancelled
            self.folder_edit.setText(folder)

    def open_folder(self):
        if self.last_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_folder)))

    # ============================================================
    # Cookies setting
    # ============================================================
    def current_cookie_settings(self):
        choice = self.cookie_box.currentData()
        if choice == "file":
            return CookieSettings(file=self.cookie_file)
        return CookieSettings(browser=choice)

    def on_cookie_choice_changed(self, *_):
        choice = self.cookie_box.currentData()

        if choice == "file":
            path, _filter = QFileDialog.getOpenFileName(
                self, "Choose your cookies.txt file", "", "Text files (*.txt);;All files (*)"
            )
            if path:
                self.cookie_file = Path(path)
            elif self.cookie_file is None:
                self.cookie_box.setCurrentIndex(0)    # cancelled and no old file: "No cookies"
                return

        shown = self.cookie_file.name if choice == "file" and self.cookie_file else ""
        self.cookie_file_label.setText(shown)

        self.downloader.cookies = self.current_cookie_settings()
        self.settings.setValue("cookies/choice", choice or "")
        if self.cookie_file:
            self.settings.setValue("cookies/file", str(self.cookie_file))

    def load_cookie_settings(self):
        """Restore the choice from the last run (without opening the file dialog)."""
        choice = self.settings.value("cookies/choice", "") or None
        saved_file = self.settings.value("cookies/file", "")
        if saved_file and Path(saved_file).exists():
            self.cookie_file = Path(saved_file)

        index = self.cookie_box.findData(choice) if choice else 0
        if index < 0 or (choice == "file" and self.cookie_file is None):
            index = 0

        self.cookie_box.blockSignals(True)       # don't run on_cookie_choice_changed now
        self.cookie_box.setCurrentIndex(index)
        self.cookie_box.blockSignals(False)

        if index != 0 and choice == "file":
            self.cookie_file_label.setText(self.cookie_file.name)
        self.downloader.cookies = self.current_cookie_settings()

    # ============================================================
    # Step A: fetch info
    # ============================================================
    def on_fetch_clicked(self):
        url = self.url_edit.text().strip()
        if not url:
            return

        self.info = None                       # the old info no longer matches the box
        self.title_label.setText("Loading...")
        self.meta_label.setText("")
        self.show_thumbnail(None)
        self.set_busy(True, "Fetching info...")

        worker = Worker(self.fetch_job, url, self.playlist_check.isChecked())
        worker.signals.finished.connect(self.on_fetched)
        worker.signals.failed.connect(self.on_failed)
        self.fetch_worker = worker             # keep a reference
        self.pool.start(worker)

    def fetch_job(self, url, playlist):
        """Runs in a BACKGROUND thread: it must not touch any widget."""
        info = self.downloader.fetch_info(url, playlist=playlist)
        return info, load_thumbnail(info.thumbnail_url)

    def on_fetched(self, result):
        """Runs in the MAIN thread (Qt delivers the signal there): widgets are safe."""
        info, thumbnail_bytes = result
        self.info = info
        self.title_label.setText(info.title)
        self.meta_label.setText(self.describe(info))
        self.show_thumbnail(thumbnail_bytes)

        if info.is_playlist:
            self.fill_qualities(PRESET_HEIGHTS)
            message = f"Playlist with {info.entry_count} items. Choose your options and press Download."
        else:
            self.fill_qualities(info.heights)
            message = "Ready. Choose your options and press Download."
        self.set_busy(False, message)

    # ============================================================
    # Step B: download
    # ============================================================
    def on_download_clicked(self):
        request = DownloadRequest(
            url=self.info.url,
            folder=Path(self.folder_edit.text()),
            mode=Mode.AUDIO if self.audio_radio.isChecked() else Mode.VIDEO,
            max_height=self.quality_box.currentData(),     # the hidden value (or None)
            playlist=self.info.is_playlist,
        )
        self.last_folder = request.folder
        self.open_button.setEnabled(False)
        self.reset_progress()
        self.set_busy(True, "Starting...")
        self.cancel_button.setEnabled(True)

        # A fresh "flag" for this download. The Cancel button raises it,
        # and the download thread checks it many times per second.
        self.cancel_event = threading.Event()

        worker = Worker(
            self.downloader.download, request,
            with_progress=True, cancel_event=self.cancel_event,
        )
        worker.signals.progress.connect(self.on_progress)
        worker.signals.finished.connect(self.on_download_done)
        worker.signals.cancelled.connect(self.on_cancelled)
        worker.signals.failed.connect(self.on_failed)
        self.download_worker = worker
        self.pool.start(worker)

    def on_cancel_clicked(self):
        if self.cancel_event is not None:
            self.cancel_event.set()                        # raise the flag
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Cancelling...")

    def on_progress(self, p):
        if p.status == "downloading":
            percent = p.percent
            prefix = ""
            if self.info and self.info.is_playlist and p.item_index:
                count = self.info.entry_count
                # Overall progress = finished items + the fraction of the current one
                percent = ((p.item_index - 1) + p.percent / 100) / count * 100
                prefix = f"Item {p.item_index}/{count}  •  "

            self.progress.setRange(0, 100)
            self.progress.setValue(int(percent))
            parts = [f"{prefix}Downloading {p.percent:.0f}%"]
            if p.speed:
                parts.append(format_speed(p.speed))
            if p.eta is not None:
                parts.append(f"{format_eta(p.eta)} left")
            self.status_label.setText("  •  ".join(parts))
        elif p.status == "processing":
            self.progress.setRange(0, 0)       # (0, 0) = a bar that just moves: "working..."
            self.status_label.setText("Processing (merging / converting)...")

    def on_download_done(self, result):
        saved = len(result.files)
        message = f"Done. {saved} file(s) saved."
        if self.info and self.info.is_playlist and saved < self.info.entry_count:
            message += f" {self.info.entry_count - saved} item(s) were skipped."

        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.cancel_button.setEnabled(False)
        self.set_busy(False, message)
        self.open_button.setEnabled(True)

    def on_cancelled(self):
        self.reset_progress()
        self.cancel_button.setEnabled(False)
        self.set_busy(False, "Cancelled. Unfinished .part files may remain in the folder.")

    # ============================================================
    # Errors (from either worker)
    # ============================================================
    def on_failed(self, message):
        self.reset_progress()
        self.cancel_button.setEnabled(False)
        self.title_label.setText(self.info.title if self.info else "Paste a link and press Fetch")
        self.set_busy(False, "Something went wrong.")
        QMessageBox.warning(self, "Media Grabber", message)