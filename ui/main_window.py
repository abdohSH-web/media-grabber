import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QThreadPool, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from grabber.downloader import Downloader
from grabber.errors import HistoryError, QueueStoreError
from grabber.history import HistoryEntry, HistoryStore
from grabber.jobs import MAX_PARALLEL, DownloadQueue, JobState
from grabber.models import CookieSettings, DownloadRequest, Mode
from grabber.queue_store import QueueStore
from grabber.tools import find_tool
from grabber.updates import installed_version, is_newer, latest_version

from .formatting import format_duration, format_eta, format_size, format_speed
from .parsing import parse_clip, parse_languages
from .playlist_dialog import PlaylistDialog
from .theme import apply_theme
from .workers import QueueBridge, Worker, load_thumbnail

# Quality choices offered for playlists (each video has its own list of heights)
PRESET_HEIGHTS = (1080, 720, 480, 360)

# The tabs, in order
TAB_DOWNLOAD, TAB_QUEUE, TAB_HISTORY, TAB_SETTINGS = range(4)

# What the Status column shows for states that need no extra details
STATE_LABELS = {
    JobState.PENDING: "Waiting",
    JobState.PAUSED: "Paused",
    JobState.DONE: "Done",
    JobState.FAILED: "Failed",
    JobState.CANCELLED: "Cancelled",
}


def make_table(headers):
    """A read-only table whose rows are selected as a whole. Used twice."""
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    return table


def item_position(job, progress):
    """Which item of the job are we on? With a hand-picked selection, positions
    are not 1, 2, 3 (they could be 4, 9, 12), so we count inside the selection."""
    items = job.request.items
    if items and progress.item_index in items:
        return items.index(progress.item_index) + 1
    return progress.item_index


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Media Grabber")
        self.resize(900, 780)

        self.downloader = Downloader()
        self.pool = QThreadPool.globalInstance()   # used for fetching info and update checks
        self.info = None              # MediaInfo of the last fetched link (None = nothing ready)
        self.selected_items = None    # chosen playlist positions (None = the whole playlist)
        self.fetch_worker = None      # we keep references so Python doesn't delete them
        self.update_worker = None

        # The queue runs in its own Python threads. The bridge hands its updates to Qt safely.
        self.bridge = QueueBridge()
        self.bridge.changed.connect(self.on_job_changed)
        self.queue = DownloadQueue(self.downloader, on_change=self.bridge.changed.emit)

        # Our files live in the app's data folder (on Windows: inside AppData)
        data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
        self.history = HistoryStore(data_dir / "history.json")
        self.queue_store = QueueStore(data_dir / "queue.json")
        self.history_entries = []     # what the History table currently shows
        self.recorded = set()         # ids of jobs already written to the history
        self.last_states = {}         # job id -> its last known state (to spot real changes)
        self.restoring = False
        self.tray = None

        # QSettings remembers small settings between runs (on Windows: in the registry)
        self.settings = QSettings("MediaGrabber", "MediaGrabber")
        self.cookie_file = None       # path of the chosen cookies.txt, if any

        self.build_ui()
        self.load_cookie_settings()
        self.queue.set_max_parallel(self.parallel_spin.value())   # the saved setting
        self.refresh_history_table()
        self.restore_queue()
        self.update_buttons()
        self.check_tools()
        self.setup_tray()

        # Restore the window size and position from the last run
        geometry = self.settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

    # ============================================================
    # Building the window
    # ============================================================
    def build_ui(self):
        # The status bar sits at the bottom of the WINDOW, so messages show on every tab
        self.status_label = QLabel("Ready")
        self.statusBar().addWidget(self.status_label, 1)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.addTab(self.build_download_tab(), "Download")
        self.tabs.addTab(self.build_queue_tab(), "Queue")
        self.tabs.addTab(self.build_history_tab(), "History")
        self.tabs.addTab(self.build_settings_tab(), "Settings")

    def build_download_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)             # stacks things top to bottom
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # A warning banner: only visible when FFmpeg or Deno is missing
        self.tools_label = QLabel("")
        self.tools_label.setObjectName("warning")       # coloured by the theme
        self.tools_label.setWordWrap(True)
        self.tools_label.setVisible(False)
        layout.addWidget(self.tools_label)

        # --- Row 1: the link + Paste + Fetch buttons ---
        link_row = QHBoxLayout()               # places things side by side
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Paste a link here...")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.returnPressed.connect(self.on_fetch_clicked)   # Enter key
        self.paste_button = QPushButton("Paste link")
        self.paste_button.clicked.connect(self.on_paste_clicked)
        self.fetch_button = QPushButton("Fetch")
        self.fetch_button.setObjectName("primary")      # the theme gives it the accent colour
        self.fetch_button.clicked.connect(self.on_fetch_clicked)
        link_row.addWidget(self.url_edit, stretch=1)    # stretch=1: takes the free space
        link_row.addWidget(self.paste_button)
        link_row.addWidget(self.fetch_button)
        layout.addLayout(link_row)

        self.playlist_check = QCheckBox("If the link belongs to a playlist, use the whole playlist")
        layout.addWidget(self.playlist_check)

        # --- Row 2: the info card (thumbnail + text) ---
        card = QHBoxLayout()
        self.thumbnail_label = QLabel("No preview")
        self.thumbnail_label.setObjectName("thumbnail")
        self.thumbnail_label.setFixedSize(240, 135)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        text_column = QVBoxLayout()
        self.title_label = QLabel("Paste a link and press Fetch")
        self.title_label.setObjectName("title")
        self.title_label.setWordWrap(True)
        self.meta_label = QLabel("")
        self.meta_label.setObjectName("muted")
        self.choose_button = QPushButton("Choose videos...")
        self.choose_button.setVisible(False)            # only shown for playlists
        self.choose_button.clicked.connect(self.on_choose_clicked)
        text_column.addWidget(self.title_label)
        text_column.addWidget(self.meta_label)
        text_column.addWidget(self.choose_button, alignment=Qt.AlignmentFlag.AlignLeft)
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

        # --- Row 3b: subtitles ---
        subs_row = QHBoxLayout()
        self.subs_check = QCheckBox("Subtitles")
        self.subs_edit = QLineEdit("ar,en")
        self.subs_edit.setPlaceholderText("language codes, e.g. en,ar")
        self.subs_auto_check = QCheckBox("include auto-generated")
        self.subs_auto_check.setChecked(True)
        self.subs_check.toggled.connect(self.update_extra_options)
        subs_row.addWidget(self.subs_check)
        subs_row.addWidget(self.subs_edit, stretch=1)
        subs_row.addWidget(self.subs_auto_check)
        layout.addLayout(subs_row)

        # --- Row 3c: download only a part of the video ---
        clip_row = QHBoxLayout()
        self.clip_check = QCheckBox("Download only a part")
        self.from_edit = QLineEdit()
        self.from_edit.setPlaceholderText("From  (0:00)")
        self.to_edit = QLineEdit()
        self.to_edit.setPlaceholderText("To  (the end)")
        self.clip_check.toggled.connect(self.update_extra_options)
        clip_row.addWidget(self.clip_check)
        clip_row.addWidget(self.from_edit, stretch=1)
        clip_row.addWidget(self.to_edit, stretch=1)
        layout.addLayout(clip_row)
        self.update_extra_options()          # start with both rows greyed out

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

        # --- Row 5: cookies (needed when YouTube asks you to prove you're not a bot) ---
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
        self.cookie_file_label.setObjectName("muted")
        cookies_row.addWidget(QLabel("Cookies:"))
        cookies_row.addWidget(self.cookie_box)
        cookies_row.addWidget(self.cookie_file_label, stretch=1)
        layout.addLayout(cookies_row)

        # --- The main button ---
        self.add_button = QPushButton("Download")
        self.add_button.setObjectName("primary")
        self.add_button.setMinimumHeight(40)
        self.add_button.setEnabled(False)              # nothing fetched yet
        self.add_button.clicked.connect(self.on_add_clicked)
        layout.addWidget(self.add_button)

        layout.addStretch()
        return page

    def build_queue_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        self.empty_label = QLabel("No downloads yet. Fetch a link in the Download tab.")
        self.empty_label.setObjectName("muted")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)

        self.table = make_table(["Title", "Status", "Size", "Speed", "Left", "Progress"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # Fixed widths: the numbers change many times a second, and the columns mustn't jump
        for column, width in ((1, 110), (2, 150), (3, 90), (4, 140), (5, 130)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(column, width)
        self.table.itemSelectionChanged.connect(self.update_buttons)
        layout.addWidget(self.table, stretch=1)

        buttons = QHBoxLayout()
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.on_pause_clicked)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.on_cancel_clicked)
        self.resume_all_button = QPushButton("Resume all")
        self.resume_all_button.clicked.connect(self.on_resume_all_clicked)
        self.open_button = QPushButton("Open folder")
        self.open_button.clicked.connect(self.open_job_folder)
        self.clear_button = QPushButton("Clear finished")
        self.clear_button.clicked.connect(self.on_clear_clicked)
        for button in (self.pause_button, self.cancel_button, self.resume_all_button,
                       self.open_button, self.clear_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        return page

    def build_history_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        self.history_table = make_table(["Finished", "Title", "Type", "Quality"])
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.itemSelectionChanged.connect(self.update_history_buttons)
        layout.addWidget(self.history_table, stretch=1)

        buttons = QHBoxLayout()
        self.history_open_button = QPushButton("Open folder")
        self.history_open_button.clicked.connect(self.on_history_open_clicked)
        self.history_again_button = QPushButton("Download again")
        self.history_again_button.clicked.connect(self.on_history_again_clicked)
        self.history_clear_button = QPushButton("Clear history")
        self.history_clear_button.clicked.connect(self.on_history_clear_clicked)
        for button in (self.history_open_button, self.history_again_button, self.history_clear_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        return page

    def build_settings_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        # --- Appearance ---
        appearance = QGroupBox("Appearance")
        form = QFormLayout(appearance)
        self.theme_box = QComboBox()
        self.theme_box.addItem("Dark", "dark")
        self.theme_box.addItem("Light", "light")
        saved_theme = self.settings.value("ui/theme", "dark")
        self.theme_box.setCurrentIndex(max(self.theme_box.findData(saved_theme), 0))
        self.theme_box.currentIndexChanged.connect(self.on_theme_changed)   # AFTER the initial value
        form.addRow("Theme", self.theme_box)
        layout.addWidget(appearance)

        # --- Downloads ---
        downloads = QGroupBox("Downloads")
        form = QFormLayout(downloads)
        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, MAX_PARALLEL)
        self.parallel_spin.setValue(self.settings.value("downloads/parallel", 1, type=int))
        self.parallel_spin.valueChanged.connect(self.on_parallel_changed)
        form.addRow("Simultaneous downloads", self.parallel_spin)
        hint = QLabel(
            "How many downloads run at the same time. More is faster only if your connection "
            "has room for it, and it can make some websites more likely to block you."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        form.addRow(hint)
        layout.addWidget(downloads)

        # --- Notifications ---
        notifications = QGroupBox("Notifications")
        form = QFormLayout(notifications)
        self.notify_check = QCheckBox("Notify me when a download finishes (if the window is in the background)")
        self.notify_check.setChecked(self.settings.value("ui/notify", True, type=bool))
        self.notify_check.toggled.connect(lambda checked: self.settings.setValue("ui/notify", checked))
        form.addRow(self.notify_check)
        layout.addWidget(notifications)

        # --- yt-dlp ---
        updates = QGroupBox("yt-dlp (the engine that talks to the websites)")
        row = QHBoxLayout(updates)
        self.version_label = QLabel(f"Installed version: {installed_version()}")
        self.update_button = QPushButton("Check for updates")
        self.update_button.clicked.connect(self.on_update_clicked)
        row.addWidget(self.version_label, stretch=1)
        row.addWidget(self.update_button)
        layout.addWidget(updates)

        layout.addStretch()
        return page

    # ============================================================
    # Settings handlers
    # ============================================================
    def on_theme_changed(self, *_):
        name = self.theme_box.currentData()
        self.settings.setValue("ui/theme", name)
        apply_theme(QApplication.instance(), name)       # switches live, no restart

    def on_parallel_changed(self, value):
        self.settings.setValue("downloads/parallel", value)
        self.queue.set_max_parallel(value)               # takes effect immediately

    # ============================================================
    # Small helpers
    # ============================================================
    def set_busy(self, busy, message):
        """Used while FETCHING: lock the buttons and show a status message."""
        self.fetch_button.setEnabled(not busy)
        self.paste_button.setEnabled(not busy)
        self.add_button.setEnabled(not busy and self.info is not None)
        self.status_label.setText(message)

    def update_options(self, *_):
        # Quality only makes sense for video
        self.quality_box.setEnabled(self.video_radio.isChecked())

    def update_extra_options(self, *_):
        """Grey out the boxes of an option that isn't switched on."""
        subs_on = self.subs_check.isChecked()
        self.subs_edit.setEnabled(subs_on)
        self.subs_auto_check.setEnabled(subs_on)

        clip_on = self.clip_check.isChecked() and self.clip_check.isEnabled()
        self.from_edit.setEnabled(clip_on)
        self.to_edit.setEnabled(clip_on)

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

    @staticmethod
    def open_in_explorer(folder):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

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
        self.selected_items = None
        self.choose_button.setVisible(False)
        self.title_label.setText("Loading...")
        self.meta_label.setText("")
        self.show_thumbnail(None)
        self.set_busy(True, "Fetching info...")

        worker = Worker(self.fetch_job, url, self.playlist_check.isChecked())
        worker.signals.finished.connect(self.on_fetched)
        worker.signals.failed.connect(self.on_fetch_failed)
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
        self.selected_items = None             # None = all videos of the playlist
        self.title_label.setText(info.title)
        self.show_thumbnail(thumbnail_bytes)
        self.choose_button.setVisible(info.is_playlist)
        self.refresh_meta()

        # Clipping makes no sense for a whole playlist
        self.clip_check.setEnabled(not info.is_playlist)
        if info.is_playlist:
            self.clip_check.setChecked(False)
        self.update_extra_options()

        if info.is_playlist:
            self.fill_qualities(PRESET_HEIGHTS)
            message = (
                f"Playlist with {info.entry_count} items. "
                "Press 'Choose videos...' to pick some, or download them all."
            )
        else:
            self.fill_qualities(info.heights)
            message = "Ready. Choose your options and press Download."
        self.set_busy(False, message)

    def on_fetch_failed(self, message):
        self.title_label.setText("Paste a link and press Fetch")
        self.set_busy(False, "Something went wrong.")
        QMessageBox.warning(self, "Media Grabber", message)

    def on_paste_clicked(self):
        text = QApplication.clipboard().text().strip()
        if not text:
            self.status_label.setText("The clipboard is empty.")
            return
        self.url_edit.setText(text)
        self.on_fetch_clicked()                # paste and fetch in one click

    def refresh_meta(self):
        """The grey line under the title (uploader, duration, selection...)."""
        if self.info is None:
            return
        text = self.describe(self.info)
        if self.info.is_playlist and self.selected_items is not None:
            text += f"  •  {len(self.selected_items)} of {self.info.entry_count} selected"
        self.meta_label.setText(text)

    def on_choose_clicked(self):
        if self.info is None or not self.info.is_playlist:
            return
        dialog = PlaylistDialog(self.info.entries, self.selected_items, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:      # the user pressed Cancel
            return

        chosen = dialog.selected_indices()
        # Everything checked = no selection needed: store None, it's simpler
        self.selected_items = None if len(chosen) == len(self.info.entries) else chosen
        self.refresh_meta()

    # ============================================================
    # Step B: the "Download" button puts a job in the queue
    # ============================================================
    def on_add_clicked(self):
        items = self.selected_items if self.info.is_playlist else None
        if items is not None and len(items) == 0:
            QMessageBox.warning(self, "Media Grabber", "Select at least one video first.")
            return

        try:
            subtitles = ()
            if self.subs_check.isChecked():
                subtitles = parse_languages(self.subs_edit.text())
                if not subtitles:
                    raise ValueError("Type at least one subtitle language, like en or ar.")

            clip_start = clip_end = None
            if self.clip_check.isChecked() and not self.info.is_playlist:
                clip_start, clip_end = parse_clip(
                    self.from_edit.text(), self.to_edit.text(), self.info.duration_seconds
                )
        except ValueError as e:                 # bad text in one of the boxes
            QMessageBox.warning(self, "Media Grabber", str(e))
            return

        request = DownloadRequest(
            url=self.info.url,
            folder=Path(self.folder_edit.text()),
            mode=Mode.AUDIO if self.audio_radio.isChecked() else Mode.VIDEO,
            max_height=self.quality_box.currentData(),     # the hidden value (or None)
            playlist=self.info.is_playlist,
            items=items,
            subtitles=subtitles,
            auto_subtitles=self.subs_auto_check.isChecked(),
            clip_start=clip_start,
            clip_end=clip_end,
        )
        count = len(items) if items else self.info.entry_count
        self.queue.add(request, self.info.title, item_count=count)
        self.status_label.setText("Added to the queue.")
        self.tabs.setCurrentIndex(TAB_QUEUE)               # take the user to the progress

    # ============================================================
    # The Queue tab
    # ============================================================
    def selected_job(self):
        """The job of the selected row, or None. Row N is always queue.jobs[N]."""
        row = self.table.currentRow()
        if 0 <= row < len(self.queue.jobs):
            return self.queue.jobs[row]
        return None

    def update_buttons(self):
        job = self.selected_job()
        state = job.state if job else None

        can_resume = state is JobState.PAUSED
        can_pause = state in (JobState.DOWNLOADING, JobState.PENDING)
        self.pause_button.setText("Resume" if can_resume else "Pause")
        self.pause_button.setEnabled(can_pause or can_resume)
        self.cancel_button.setEnabled(
            state in (JobState.PENDING, JobState.DOWNLOADING, JobState.PAUSED)
        )
        self.open_button.setEnabled(job is not None)
        self.resume_all_button.setEnabled(
            any(j.state is JobState.PAUSED for j in self.queue.jobs)
        )

        # A hint when the queue is empty, and a count in the tab's title
        self.empty_label.setVisible(len(self.queue.jobs) == 0)
        unfinished = sum(
            1 for j in self.queue.jobs
            if j.state in (JobState.PENDING, JobState.DOWNLOADING, JobState.PAUSED)
        )
        self.tabs.setTabText(TAB_QUEUE, f"Queue ({unfinished})" if unfinished else "Queue")

    def on_pause_clicked(self):
        job = self.selected_job()
        if job is None:
            return
        if job.state is JobState.PAUSED:
            self.queue.resume(job)
        else:
            self.queue.pause(job)

    def on_cancel_clicked(self):
        job = self.selected_job()
        if job is not None:
            self.queue.cancel(job)

    def on_resume_all_clicked(self):
        for job in list(self.queue.jobs):
            if job.state is JobState.PAUSED:
                self.queue.resume(job)

    def open_job_folder(self):
        job = self.selected_job()
        if job is not None:
            self.open_in_explorer(job.request.folder)

    def on_clear_clicked(self):
        self.queue.clear_finished()
        self.rebuild_table()

    # ---------- keeping the table in sync with the queue ----------
    def on_job_changed(self, job):
        """Runs in the MAIN thread, every time the queue reports a change."""
        self.update_row(job)
        self.update_buttons()

        # Save the queue only when a job APPEARS or CHANGES STATE (not on every progress tick)
        previous_state = self.last_states.get(job.id)
        self.last_states[job.id] = job.state
        if job.state is not previous_state and not self.restoring:
            self.save_queue()

        # A finished job is written to the history exactly once
        if job.state is JobState.DONE and job.id not in self.recorded:
            self.recorded.add(job.id)
            self.record_history(job)
            self.notify_done(job)

    def save_queue(self):
        try:
            self.queue_store.save(self.queue.jobs)
        except QueueStoreError as e:
            self.status_label.setText(f"Couldn't save the queue: {e}")

    def restore_queue(self):
        """Bring back the unfinished jobs of the last session, PAUSED."""
        self.restoring = True
        try:
            for request, title, item_count in self.queue_store.load():
                self.queue.add(request, title, item_count, paused=True)
        finally:
            self.restoring = False

        count = len(self.queue.jobs)
        if count:
            self.save_queue()
            self.status_label.setText(
                f"Restored {count} unfinished download(s). Open the Queue tab and press Resume all."
            )

    def ensure_row(self, row):
        """Make sure the table has a row number `row` (with its progress bar)."""
        while self.table.rowCount() <= row:
            new_row = self.table.rowCount()
            self.table.insertRow(new_row)
            for column in range(5):                    # the five text columns
                self.table.setItem(new_row, column, QTableWidgetItem(""))
            bar = QProgressBar()
            bar.setRange(0, 100)
            self.table.setCellWidget(new_row, 5, bar)  # the last column

    def update_row(self, job):
        try:
            row = self.queue.jobs.index(job)
        except ValueError:
            return                                     # the job was cleared meanwhile
        self.ensure_row(row)

        texts = (
            job.title,
            self.status_text(job),
            self.size_text(job),
            self.speed_text(job),
            self.left_text(job),
        )
        for column, text in enumerate(texts):
            self.table.item(row, column).setText(text)
        self.table.item(row, 1).setToolTip(job.message if job.state is JobState.FAILED else "")
        self.table.cellWidget(row, 5).setValue(int(self.job_percent(job)))

    def rebuild_table(self):
        self.table.setRowCount(0)
        for job in list(self.queue.jobs):
            self.update_row(job)
        self.update_buttons()

    @staticmethod
    def status_text(job):
        if job.state is not JobState.DOWNLOADING:
            return STATE_LABELS[job.state]

        p = job.progress
        if p is None:
            return "Starting..."
        if p.status == "processing":
            return "Processing..."
        if job.item_count > 1 and p.item_index:
            return f"Item {item_position(job, p)}/{job.item_count}"
        return "Downloading"

    @staticmethod
    def size_text(job):
        """'125.3 MB / 480.2 MB' while downloading, the final size when done."""
        if job.state is JobState.DONE:
            return format_size(job.size_bytes) if job.size_bytes else ""
        p = job.progress
        if p is None or not p.downloaded_bytes:
            return ""
        if p.total_bytes:
            return f"{format_size(p.downloaded_bytes)} / {format_size(p.total_bytes)}"
        return format_size(p.downloaded_bytes)

    @staticmethod
    def speed_text(job):
        p = job.progress
        if job.state is JobState.DOWNLOADING and p and p.status == "downloading" and p.speed:
            return format_speed(p.speed)
        return ""

    @staticmethod
    def left_text(job):
        """What remains: the size and the time, like '354.9 MB  •  1:02'."""
        p = job.progress
        if job.state is not JobState.DOWNLOADING or p is None or p.status != "downloading":
            return ""
        parts = []
        if p.total_bytes and p.downloaded_bytes is not None:
            parts.append(format_size(max(p.total_bytes - p.downloaded_bytes, 0)))
        if p.eta is not None:
            parts.append(format_eta(p.eta))
        return "  •  ".join(parts)

    @staticmethod
    def job_percent(job):
        if job.state is JobState.DONE:
            return 100
        p = job.progress
        if p is None:
            return 0
        if job.item_count > 1 and p.item_index:
            # Overall progress = finished items + the fraction of the current one
            return ((item_position(job, p) - 1) + p.percent / 100) / job.item_count * 100
        return p.percent

    # ============================================================
    # History
    # ============================================================
    def record_history(self, job):
        entry = HistoryEntry(
            title=job.title,
            url=job.request.url,
            mode=job.request.mode.value,
            max_height=job.request.max_height,
            playlist=job.request.playlist,
            folder=str(job.request.folder),
            finished_at=datetime.now().isoformat(timespec="seconds"),
            file_count=len(job.files),
            items=list(job.request.items) if job.request.items else None,
            subtitles=list(job.request.subtitles) if job.request.subtitles else None,
            auto_subtitles=job.request.auto_subtitles,
            clip_start=job.request.clip_start,
            clip_end=job.request.clip_end,
        )
        try:
            self.history.add(entry)
        except HistoryError as e:
            self.status_label.setText(f"Couldn't save the history: {e}")
        self.refresh_history_table()

    def refresh_history_table(self):
        self.history_entries = self.history.load()          # newest first
        self.history_table.setRowCount(len(self.history_entries))

        for row, entry in enumerate(self.history_entries):
            if entry.mode == "audio":
                quality = "MP3"
            else:
                quality = f"Up to {entry.max_height}p" if entry.max_height else "Best"
            kind = entry.mode.capitalize() + ("  •  playlist" if entry.playlist else "")
            cells = (entry.finished_at.replace("T", " "), entry.title, kind, quality)
            for column, text in enumerate(cells):
                self.history_table.setItem(row, column, QTableWidgetItem(text))
        self.update_history_buttons()

    def selected_history_entry(self):
        row = self.history_table.currentRow()
        if 0 <= row < len(self.history_entries):
            return self.history_entries[row]
        return None

    def update_history_buttons(self):
        selected = self.selected_history_entry() is not None
        self.history_open_button.setEnabled(selected)
        self.history_again_button.setEnabled(selected)
        self.history_clear_button.setEnabled(bool(self.history_entries))

    def on_history_open_clicked(self):
        entry = self.selected_history_entry()
        if entry is not None:
            self.open_in_explorer(entry.folder)

    def on_history_again_clicked(self):
        entry = self.selected_history_entry()
        if entry is None:
            return
        items = tuple(entry.items) if entry.items else None
        request = DownloadRequest(
            url=entry.url,
            folder=Path(entry.folder),
            mode=Mode(entry.mode),                 # "video" -> Mode.VIDEO
            max_height=entry.max_height,
            playlist=entry.playlist,
            items=items,
            subtitles=tuple(entry.subtitles or ()),
            auto_subtitles=entry.auto_subtitles,
            clip_start=entry.clip_start,
            clip_end=entry.clip_end,
        )
        item_count = len(items) if items else (entry.file_count if entry.playlist else 1)
        self.queue.add(request, entry.title, item_count=item_count)
        self.tabs.setCurrentIndex(TAB_QUEUE)       # jump to the progress
        self.status_label.setText("Added to the queue.")

    def on_history_clear_clicked(self):
        answer = QMessageBox.question(self, "Media Grabber", "Clear the whole download history?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.history.clear()
        except HistoryError as e:
            QMessageBox.warning(self, "Media Grabber", str(e))
        self.refresh_history_table()

    # ============================================================
    # Tools check and yt-dlp updates
    # ============================================================
    def check_tools(self):
        """Show a warning banner if a tool we depend on is missing."""
        problems = []
        if not find_tool("ffmpeg"):
            problems.append(
                "⚠ FFmpeg wasn't found, so downloads won't work. "
                "Install it with:  winget install Gyan.FFmpeg  and restart the app."
            )
        if not find_tool("deno"):
            problems.append(
                "⚠ Deno wasn't found: some YouTube formats may be missing. "
                "Install it with:  winget install DenoLand.Deno  and restart the app."
            )
        self.tools_label.setText("\n".join(problems))
        self.tools_label.setVisible(bool(problems))

    def on_update_clicked(self):
        self.update_button.setEnabled(False)
        self.status_label.setText("Checking for a newer yt-dlp...")

        worker = Worker(latest_version)          # runs in the background: it uses the internet
        worker.signals.finished.connect(self.on_update_checked)
        self.update_worker = worker              # keep a reference
        self.pool.start(worker)

    def on_update_checked(self, latest):
        self.update_button.setEnabled(True)
        current = installed_version()

        if latest is None:
            self.status_label.setText("Couldn't check for updates (no internet?).")
            return
        if not is_newer(latest, current):
            self.status_label.setText(f"yt-dlp is up to date ({current}).")
            return

        if getattr(sys, "frozen", False):        # the packaged .exe
            how = "Rebuild the app with build.ps1: it installs the newest yt-dlp first."
        else:                                    # running from source
            how = 'Update it with:  pip install -U "yt-dlp[default]"'
        QMessageBox.information(
            self, "Media Grabber",
            f"A newer yt-dlp is available: {latest} (you have {current}).\n\n{how}",
        )
        self.status_label.setText(f"Update available: yt-dlp {latest}")

    # ============================================================
    # Notifications
    # ============================================================
    def setup_tray(self):
        """A system-tray icon: it is what lets us show Windows notifications."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = QApplication.windowIcon()
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("Media Grabber")
        self.tray.show()

    def notify_done(self, job):
        """Tell the user a download finished, but only when they aren't looking at the window."""
        if self.tray is None or not self.notify_check.isChecked() or self.isActiveWindow():
            return
        still_busy = any(
            j.state in (JobState.PENDING, JobState.DOWNLOADING) for j in self.queue.jobs
        )
        title = "Download finished" if still_busy else "All downloads finished"
        self.tray.showMessage(title, job.title, QSystemTrayIcon.MessageIcon.Information, 6000)

    def closeEvent(self, event):
        """Qt calls this when the window is closing: save its size and position."""
        self.settings.setValue("window/geometry", self.saveGeometry())
        if self.tray is not None:
            self.tray.hide()                  # so no ghost icon stays behind
        super().closeEvent(event)