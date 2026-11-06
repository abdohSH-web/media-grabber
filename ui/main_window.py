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
    QFrame,
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
    QScrollArea,
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
from grabber.naming import safe_folder_name
from grabber.queue_store import QueueStore
from grabber.tools import add_to_path, find_tool
from grabber.toolsetup import install_tools, missing_tools
from grabber.version import APP_VERSION
from grabber.updates import installed_version, is_newer, latest_version

from .clip_dialog import ClipDialog
from .formatting import format_duration, format_eta, format_size, format_speed
from .i18n import LANGUAGES, apply_language, current_language, tr, error_text
from .parsing import parse_languages
from .playlist_dialog import PlaylistDialog
from .theme import apply_theme
from .workers import QueueBridge, Worker, load_thumbnail

# Quality choices offered for playlists (each video has its own list of heights)
PRESET_HEIGHTS = (1080, 720, 480, 360)

TOOL_LABELS = {"ffmpeg": "FFmpeg", "deno": "Deno"}

# The tabs, in order
TAB_DOWNLOAD, TAB_QUEUE, TAB_HISTORY, TAB_SETTINGS = range(4)

# State -> the translation key of its label (the other states need details)
STATE_KEYS = {
    JobState.PENDING: "state_waiting",
    JobState.PAUSED: "state_paused",
    JobState.DONE: "state_done",
    JobState.FAILED: "state_failed",
    JobState.CANCELLED: "state_cancelled",
}

# (translation key of the visible text, hidden value)
COOKIE_CHOICES = (
    ("cookies_none", None), ("cookies_firefox", "firefox"), ("cookies_edge", "edge"),
    ("cookies_chrome", "chrome"), ("cookies_brave", "brave"), ("cookies_file", "file"),
)
THEME_CHOICES = (("theme_dark", "dark"), ("theme_light", "light"))


def make_table(columns):
    """A read-only table whose rows are selected as a whole. Used twice."""
    table = QTableWidget(0, columns)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    return table


def item_position(job, progress):
    """Which item of an (older) playlist job are we on? With a hand-picked selection,
    positions are not 1, 2, 3, so we count inside the selection."""
    items = job.request.items
    if items and progress.item_index in items:
        return items.index(progress.item_index) + 1
    return progress.item_index


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Media Grabber")
        self.resize(900, 780)

        # Functions that write the texts again when the language changes (see bind())
        self._refreshers = []

        self.downloader = Downloader()
        self.pool = QThreadPool.globalInstance()   # used for fetching info and update checks
        self.info = None              # MediaInfo of the last fetched link (None = nothing ready)
        self.loading = False
        self.has_thumbnail = False
        self.quality_heights = ()
        self.selected_items = None    # chosen playlist positions (None = the whole playlist)
        self.clip_range = None        # (start, end) in seconds chosen in the clip window, or None
        self.fetch_worker = None      # we keep references so Python doesn't delete them
        self.update_worker = None
        self.tools_busy = False       # True while FFmpeg / Deno are being downloaded
        self.tools_worker = None

        # The queue runs in its own Python threads. The bridge hands its updates to Qt safely.
        self.bridge = QueueBridge()
        self.bridge.changed.connect(self.on_job_changed)
        self.queue = DownloadQueue(self.downloader, on_change=self.bridge.changed.emit)

        # Our files live in the app's data folder (on Windows: inside AppData)
        data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
        self.tools_folder = data_dir / "tools"    # where "Download tools" puts FFmpeg and Deno
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
        self.setup_tray()
        self.retranslate_ui()         # writes every text in the current language
        self.restore_queue()          # AFTER retranslate_ui: it sets the status message
        self.update_buttons()

        # Restore the window size and position from the last run
        geometry = self.settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

    # ============================================================
    # Translation helpers
    # ============================================================
    def refresher(self, function):
        """Run `function` now, and again every time the language changes."""
        self._refreshers.append(function)
        function()

    def bind(self, setter, key, **values):
        """Show the text `key` through `setter` (like label.setText), now and after each language change."""
        self.refresher(lambda: setter(tr(key, **values)))

    def bind_headers(self, table, keys):
        self.refresher(lambda: table.setHorizontalHeaderLabels([tr(key) for key in keys]))

    def bind_items(self, combo, keys):
        """Translate the VISIBLE text of a combo box's items (their hidden values don't change)."""
        def refresh():
            for index, key in enumerate(keys):
                combo.setItemText(index, tr(key))
        self.refresher(refresh)

    def label(self, key, name=None):
        widget = QLabel()
        if name:
            widget.setObjectName(name)
        self.bind(widget.setText, key)
        return widget

    def button(self, key, name=None):
        widget = QPushButton()
        if name:
            widget.setObjectName(name)
        self.bind(widget.setText, key)
        return widget

    def check(self, key):
        widget = QCheckBox()
        self.bind(widget.setText, key)
        return widget

    def radio(self, key):
        widget = QRadioButton()
        self.bind(widget.setText, key)
        return widget

    def retranslate_ui(self):
        """Write every text again. Runs at start-up and when the language changes."""
        for refresh in self._refreshers:
            refresh()
        # Texts built from the current state, not from one fixed key
        self.fill_qualities(self.quality_heights, keep_choice=True)
        self.refresh_title()
        self.refresh_meta()
        self.refresh_clip_label()
        if not self.has_thumbnail:
            self.thumbnail_label.setText(tr("thumb_none"))
        self.refresh_history_table()
        self.rebuild_table()                      # also runs update_buttons()
        self.check_tools()
        self.status_label.setText(tr("status_ready"))

    # ---------- message boxes with translated buttons ----------
    def message(self, icon, text):
        box = QMessageBox(icon, "Media Grabber", text, parent=self)
        box.addButton(tr("btn_ok"), QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    def warn(self, text):
        self.message(QMessageBox.Icon.Warning, text)

    def inform(self, text):
        self.message(QMessageBox.Icon.Information, text)

    def ask(self, text):
        box = QMessageBox(QMessageBox.Icon.Question, "Media Grabber", text, parent=self)
        yes = box.addButton(tr("btn_yes"), QMessageBox.ButtonRole.YesRole)
        box.addButton(tr("btn_no"), QMessageBox.ButtonRole.NoRole)
        box.exec()
        return box.clickedButton() is yes

    # ============================================================
    # Building the window
    # ============================================================
    def build_ui(self):
        # The status bar sits at the bottom of the WINDOW, so messages show on every tab
        self.status_label = QLabel()
        self.statusBar().addWidget(self.status_label, 1)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.addTab(self.build_download_tab(), "")
        self.tabs.addTab(self.build_queue_tab(), "")
        self.tabs.addTab(self.build_history_tab(), "")
        self.tabs.addTab(self.build_settings_tab(), "")
        # The Queue tab's title carries a count, so update_buttons() writes it
        for index, key in ((TAB_DOWNLOAD, "tab_download"), (TAB_HISTORY, "tab_history"),
                           (TAB_SETTINGS, "tab_settings")):
            self.bind(lambda text, i=index: self.tabs.setTabText(i, text), key)

    def build_download_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # A warning banner with a button: only visible when FFmpeg or Deno is missing
        tools_row = QHBoxLayout()
        self.tools_label = QLabel("")
        self.tools_label.setObjectName("warning")
        self.tools_label.setWordWrap(True)
        self.tools_button = self.button("btn_download_tools")
        self.tools_button.clicked.connect(self.on_download_tools_clicked)
        self.tools_label.setVisible(False)
        self.tools_button.setVisible(False)
        tools_row.addWidget(self.tools_label, stretch=1)
        tools_row.addWidget(self.tools_button)
        layout.addLayout(tools_row)

        # --- Row 1: the link + Paste + Fetch buttons ---
        link_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setClearButtonEnabled(True)
        self.bind(self.url_edit.setPlaceholderText, "url_placeholder")
        self.url_edit.returnPressed.connect(self.on_fetch_clicked)
        self.paste_button = self.button("btn_paste")
        self.paste_button.clicked.connect(self.on_paste_clicked)
        self.fetch_button = self.button("btn_fetch", "primary")
        self.fetch_button.clicked.connect(self.on_fetch_clicked)
        link_row.addWidget(self.url_edit, stretch=1)
        link_row.addWidget(self.paste_button)
        link_row.addWidget(self.fetch_button)
        layout.addLayout(link_row)

        self.playlist_check = self.check("chk_playlist")
        layout.addWidget(self.playlist_check)

        # --- Row 2: the info card (thumbnail + text) ---
        card = QHBoxLayout()
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setObjectName("thumbnail")
        self.thumbnail_label.setFixedSize(240, 135)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        text_column = QVBoxLayout()
        self.title_label = QLabel()
        self.title_label.setObjectName("title")
        self.title_label.setWordWrap(True)
        self.meta_label = QLabel()
        self.meta_label.setObjectName("muted")
        self.choose_button = self.button("btn_choose_videos")
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
        self.video_radio = self.radio("opt_video")
        self.audio_radio = self.radio("opt_audio")
        self.video_radio.setChecked(True)
        self.video_radio.toggled.connect(self.update_options)
        self.quality_box = QComboBox()
        self.fill_qualities(())
        options_row.addWidget(self.video_radio)
        options_row.addWidget(self.audio_radio)
        options_row.addWidget(self.label("lbl_quality"))
        options_row.addWidget(self.quality_box, stretch=1)
        layout.addLayout(options_row)

        # --- Row 3b: subtitles ---
        subs_row = QHBoxLayout()
        self.subs_check = self.check("chk_subs")
        self.subs_edit = QLineEdit("ar,en")
        self.bind(self.subs_edit.setPlaceholderText, "subs_placeholder")
        self.subs_auto_check = self.check("chk_subs_auto")
        self.subs_auto_check.setChecked(True)
        self.subs_check.toggled.connect(self.update_extra_options)
        subs_row.addWidget(self.subs_check)
        subs_row.addWidget(self.subs_edit, stretch=1)
        subs_row.addWidget(self.subs_auto_check)
        layout.addLayout(subs_row)

        # --- Row 3c: download only a part of the video ---
        clip_row = QHBoxLayout()
        self.clip_check = self.check("chk_clip")
        self.clip_check.toggled.connect(self.on_clip_toggled)
        self.clip_button = self.button("btn_choose_clip")
        self.clip_button.clicked.connect(self.on_choose_clip_clicked)
        self.clip_label = QLabel()
        self.clip_label.setObjectName("muted")
        clip_row.addWidget(self.clip_check)
        clip_row.addWidget(self.clip_button)
        clip_row.addWidget(self.clip_label, stretch=1)
        layout.addLayout(clip_row)
        self.update_extra_options()          # start with the greyed-out look

        # --- Row 4: where to save ---
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(str(Path.home() / "Downloads"))
        self.folder_edit.setReadOnly(True)
        browse_button = self.button("btn_browse")
        browse_button.clicked.connect(self.choose_folder)
        folder_row.addWidget(self.label("lbl_save_to"))
        folder_row.addWidget(self.folder_edit, stretch=1)
        folder_row.addWidget(browse_button)
        layout.addLayout(folder_row)

        # --- Row 5: cookies (needed when YouTube asks you to prove you're not a bot) ---
        cookies_row = QHBoxLayout()
        self.cookie_box = QComboBox()
        self.bind(self.cookie_box.setToolTip, "cookies_tooltip")
        for _key, value in COOKIE_CHOICES:
            self.cookie_box.addItem("", value)         # the visible text comes from bind_items
        self.bind_items(self.cookie_box, [key for key, _value in COOKIE_CHOICES])
        self.cookie_box.currentIndexChanged.connect(self.on_cookie_choice_changed)
        self.cookie_file_label = QLabel("")
        self.cookie_file_label.setObjectName("muted")
        cookies_row.addWidget(self.label("lbl_cookies"))
        cookies_row.addWidget(self.cookie_box)
        cookies_row.addWidget(self.cookie_file_label, stretch=1)
        layout.addLayout(cookies_row)

        # --- The main button ---
        self.add_button = self.button("btn_download", "primary")
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

        self.empty_label = self.label("queue_empty", "muted")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)

        self.table = make_table(6)
        self.bind_headers(self.table, ["col_title", "col_status", "col_size",
                                       "col_speed", "col_left", "col_progress"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # Fixed widths: the numbers change many times a second, and the columns mustn't jump
        for column, width in ((1, 110), (2, 150), (3, 90), (4, 140), (5, 130)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(column, width)
        self.table.itemSelectionChanged.connect(self.update_buttons)
        layout.addWidget(self.table, stretch=1)

        buttons = QHBoxLayout()
        self.pause_button = QPushButton()               # its text (Pause/Resume) follows the selection
        self.pause_button.clicked.connect(self.on_pause_clicked)
        self.cancel_button = self.button("btn_cancel")
        self.cancel_button.clicked.connect(self.on_cancel_clicked)
        self.pause_all_button = self.button("btn_pause_all")
        self.pause_all_button.clicked.connect(self.on_pause_all_clicked)
        self.resume_all_button = self.button("btn_resume_all")
        self.resume_all_button.clicked.connect(self.on_resume_all_clicked)
        self.open_button = self.button("btn_open_folder")
        self.open_button.clicked.connect(self.open_job_folder)
        self.clear_button = self.button("btn_clear_finished")
        self.clear_button.clicked.connect(self.on_clear_clicked)
        for button in (self.pause_button, self.cancel_button, self.pause_all_button,
                       self.resume_all_button, self.open_button, self.clear_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        return page

    def build_history_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        self.history_table = make_table(4)
        self.bind_headers(self.history_table, ["hcol_finished", "col_title", "hcol_type", "hcol_quality"])
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.itemSelectionChanged.connect(self.update_history_buttons)
        layout.addWidget(self.history_table, stretch=1)

        buttons = QHBoxLayout()
        self.history_open_button = self.button("btn_open_folder")
        self.history_open_button.clicked.connect(self.on_history_open_clicked)
        self.history_again_button = self.button("btn_download_again")
        self.history_again_button.clicked.connect(self.on_history_again_clicked)
        self.history_clear_button = self.button("btn_clear_history")
        self.history_clear_button.clicked.connect(self.on_history_clear_clicked)
        for button in (self.history_open_button, self.history_again_button, self.history_clear_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        return page

    def build_settings_tab(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 20)

        def new_form(group, grow=False):
            """The same comfortable spacing for every group."""
            form = QFormLayout(group)
            form.setHorizontalSpacing(18)
            form.setVerticalSpacing(12)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignVCenter)
            policy = (QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow if grow
                      else QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
            form.setFieldGrowthPolicy(policy)
            return form

        # --- Appearance: theme and language ---
        appearance = QGroupBox()
        self.bind(appearance.setTitle, "grp_appearance")
        form = new_form(appearance)

        self.theme_box = QComboBox()
        self.theme_box.setMinimumWidth(220)
        for _key, value in THEME_CHOICES:
            self.theme_box.addItem("", value)
        self.bind_items(self.theme_box, [key for key, _value in THEME_CHOICES])
        saved_theme = self.settings.value("ui/theme", "dark")
        self.theme_box.setCurrentIndex(max(self.theme_box.findData(saved_theme), 0))
        self.theme_box.currentIndexChanged.connect(self.on_theme_changed)   # AFTER the initial value
        form.addRow(self.label("lbl_theme"), self.theme_box)

        self.language_box = QComboBox()
        self.language_box.setMinimumWidth(220)
        for code, name in LANGUAGES:                    # each language is named in ITS OWN language
            self.language_box.addItem(name, code)
        self.language_box.setCurrentIndex(max(self.language_box.findData(current_language()), 0))
        self.language_box.currentIndexChanged.connect(self.on_language_changed)
        form.addRow(self.label("lbl_language"), self.language_box)
        layout.addWidget(appearance)

        # --- Downloads ---
        downloads = QGroupBox()
        self.bind(downloads.setTitle, "grp_downloads")
        form = new_form(downloads)
        self.parallel_spin = QSpinBox()
        self.parallel_spin.setMinimumWidth(90)
        self.parallel_spin.setRange(1, MAX_PARALLEL)
        self.parallel_spin.setValue(self.settings.value("downloads/parallel", 1, type=int))
        self.parallel_spin.valueChanged.connect(self.on_parallel_changed)
        form.addRow(self.label("lbl_parallel"), self.parallel_spin)
        hint = self.label("parallel_hint", "muted")
        hint.setWordWrap(True)
        form.addRow(hint)
        layout.addWidget(downloads)

        # --- Notifications ---
        notifications = QGroupBox()
        self.bind(notifications.setTitle, "grp_notifications")
        form = new_form(notifications)
        self.notify_check = self.check("chk_notify")
        self.notify_check.setChecked(self.settings.value("ui/notify", True, type=bool))
        self.notify_check.toggled.connect(lambda checked: self.settings.setValue("ui/notify", checked))
        form.addRow(self.notify_check)
        layout.addWidget(notifications)

        # --- yt-dlp ---
        updates = QGroupBox()
        self.bind(updates.setTitle, "grp_engine")
        row = QHBoxLayout(updates)
        self.version_label = QLabel()
        self.bind(self.version_label.setText, "lbl_installed_version", version=installed_version())
        self.update_button = self.button("btn_check_updates")
        self.update_button.clicked.connect(self.on_update_clicked)
        row.addWidget(self.version_label, stretch=1)
        row.addWidget(self.update_button)
        layout.addWidget(updates)

        # --- Required tools ---
        tools = QGroupBox()
        self.bind(tools.setTitle, "grp_tools")
        form = new_form(tools, grow=True)
        self.ffmpeg_status = QLabel()
        self.deno_status = QLabel()
        for status in (self.ffmpeg_status, self.deno_status):
            status.setWordWrap(True)                    # a long path wraps instead of being cut
            status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("FFmpeg", self.ffmpeg_status)
        form.addRow("Deno", self.deno_status)
        self.tools_download_button = self.button("btn_download_tools")
        self.tools_download_button.clicked.connect(self.on_download_tools_clicked)
        form.addRow(self.tools_download_button)
        layout.addWidget(tools)

        about = QLabel()
        about.setObjectName("muted")
        self.bind(about.setText, "lbl_about", version=APP_VERSION)
        layout.addWidget(about)

        layout.addStretch()

        # The page scrolls when the window is short, instead of squeezing everything
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    # ============================================================
    # Settings handlers
    # ============================================================
    def on_theme_changed(self, *_):
        name = self.theme_box.currentData()
        self.settings.setValue("ui/theme", name)
        apply_theme(QApplication.instance(), name)       # switches live, no restart

    def on_language_changed(self, *_):
        code = self.language_box.currentData()
        self.settings.setValue("ui/language", code)
        apply_language(QApplication.instance(), code)    # language AND direction (RTL for Arabic)
        self.retranslate_ui()

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
        self.clip_button.setEnabled(clip_on)

    def fill_qualities(self, heights, keep_choice=False):
        self.quality_heights = tuple(heights)
        previous = self.quality_box.currentIndex()
        self.quality_box.clear()
        self.quality_box.addItem(tr("quality_best"), None)       # (text, hidden value)
        for height in heights:
            # The hidden value is a NUMBER: it becomes DownloadRequest.max_height
            self.quality_box.addItem(tr("quality_upto", height=height), height)
        if keep_choice and 0 <= previous < self.quality_box.count():
            self.quality_box.setCurrentIndex(previous)

    def show_thumbnail(self, data):
        pixmap = QPixmap()
        self.has_thumbnail = bool(data) and pixmap.loadFromData(data)
        if self.has_thumbnail:
            self.thumbnail_label.setPixmap(pixmap.scaled(
                self.thumbnail_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            self.thumbnail_label.setPixmap(QPixmap())    # clears the old image
            self.thumbnail_label.setText(tr("thumb_none"))

    def refresh_title(self):
        if self.info is not None:
            self.title_label.setText(self.info.title)
        elif self.loading:
            self.title_label.setText(tr("title_loading"))
        else:
            self.title_label.setText(tr("title_placeholder"))

    @staticmethod
    def describe(info):
        parts = [info.uploader]
        if info.duration_seconds:
            parts.append(format_duration(info.duration_seconds))
        if info.is_playlist:
            parts.append(tr("meta_items", count=info.entry_count))
        return "  •  ".join(parts)

    def refresh_meta(self):
        """The grey line under the title (uploader, duration, selection...)."""
        if self.info is None:
            self.meta_label.setText("")
            return
        text = self.describe(self.info)
        if self.info.is_playlist and self.selected_items is not None:
            text += "  •  " + tr("meta_selected", chosen=len(self.selected_items),
                                  total=self.info.entry_count)
        self.meta_label.setText(text)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("dlg_choose_folder"), self.folder_edit.text())
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
                self, tr("dlg_choose_cookies"), "", tr("dlg_cookies_filter")
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
        self.loading = True
        self.selected_items = None
        self.clip_range = None                 # a new video: the old range means nothing
        self.clip_check.setChecked(False)
        self.choose_button.setVisible(False)
        self.refresh_title()
        self.meta_label.setText("")
        self.show_thumbnail(None)
        self.set_busy(True, tr("status_fetching"))

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
        self.loading = False
        self.info = info
        self.selected_items = None             # None = all videos of the playlist
        self.show_thumbnail(thumbnail_bytes)
        self.choose_button.setVisible(info.is_playlist)
        self.refresh_title()
        self.refresh_meta()

        # Clipping makes no sense for a whole playlist
        self.clip_check.setEnabled(not info.is_playlist)
        if info.is_playlist:
            self.clip_check.setChecked(False)
        self.update_extra_options()

        if info.is_playlist:
            self.fill_qualities(PRESET_HEIGHTS)
            message = tr("status_ready_playlist", count=info.entry_count)
        else:
            self.fill_qualities(info.heights)
            message = tr("status_ready_single")
        self.set_busy(False, message)

    def on_fetch_failed(self, error):
        self.loading = False
        self.refresh_title()
        self.set_busy(False, tr("status_error"))
        self.warn(error_text(error))           # translated when the error has a code

    def on_paste_clicked(self):
        text = QApplication.clipboard().text().strip()
        if not text:
            self.status_label.setText(tr("status_clipboard_empty"))
            return
        self.url_edit.setText(text)
        self.on_fetch_clicked()                # paste and fetch in one click

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

    # ---------- download only a part ----------
    def on_clip_toggled(self, checked):
        self.update_extra_options()
        if checked and self.clip_range is None:
            self.on_choose_clip_clicked()        # open the window right away
        self.refresh_clip_label()

    def on_choose_clip_clicked(self):
        if self.info is None or not self.info.duration_seconds:
            self.warn(tr("warn_fetch_first"))
            self.clip_check.setChecked(False)
            return

        start, end = self.clip_range if self.clip_range else (None, None)
        dialog = ClipDialog(self.info.duration_seconds, start, end, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            start, end = dialog.selected_range()
            # (None, None) = the whole video = nothing to clip
            self.clip_range = None if start is None else (start, end)

        if self.clip_range is None:               # cancelled, or "whole video"
            self.clip_check.setChecked(False)
        self.refresh_clip_label()

    def refresh_clip_label(self):
        if not self.clip_check.isChecked() or self.clip_range is None:
            self.clip_label.setText("")
            return
        start, end = self.clip_range
        end_text = format_duration(end) if end is not None else tr("clip_end")
        self.clip_label.setText(tr("clip_range", start=format_duration(start), end=end_text))

    # ============================================================
    # Step B: the "Download" button puts jobs in the queue
    # ============================================================
    def on_add_clicked(self):
        if self.info.is_playlist and self.selected_items is not None and len(self.selected_items) == 0:
            self.warn(tr("warn_select_one"))
            return

        try:
            subtitles = ()
            if self.subs_check.isChecked():
                subtitles = parse_languages(self.subs_edit.text())
                if not subtitles:
                    raise ValueError(tr("warn_subs_language"))

            clip_start = clip_end = None
            if self.clip_check.isChecked() and not self.info.is_playlist:
                if self.clip_range is None:
                    raise ValueError(tr("warn_choose_part"))
                clip_start, clip_end = self.clip_range
        except ValueError as e:                 # something is missing or wrong
            self.warn(str(e))
            return

        # Everything the jobs share
        common = dict(
            mode=Mode.AUDIO if self.audio_radio.isChecked() else Mode.VIDEO,
            max_height=self.quality_box.currentData(),     # the hidden value (or None)
            subtitles=subtitles,
            auto_subtitles=self.subs_auto_check.isChecked(),
            clip_start=clip_start,
            clip_end=clip_end,
        )
        base_folder = Path(self.folder_edit.text())

        if self.info.is_playlist:
            if not self.add_playlist_as_jobs(base_folder, common):
                return
        else:
            request = DownloadRequest(url=self.info.url, folder=base_folder, **common)
            self.queue.add(request, self.info.title)
            self.status_label.setText(tr("status_added"))
        self.tabs.setCurrentIndex(TAB_QUEUE)               # take the user to the progress

    def add_playlist_as_jobs(self, base_folder, common):
        """One job PER VIDEO, so every queue feature (parallel downloads, pause, cancel...)
        works on each video. Returns False if nothing was added."""
        chosen = [
            entry for entry in self.info.entries
            if self.selected_items is None or entry.index in self.selected_items
        ]
        usable = [entry for entry in chosen if entry.url]      # an entry without a link can't be downloaded
        if not usable:
            self.warn(tr("warn_no_valid_items"))
            return False

        folder = base_folder / safe_folder_name(self.info.title)   # a subfolder named like the playlist
        width = len(str(max(entry.index for entry in self.info.entries)))   # 03 or 003...
        for entry in usable:
            request = DownloadRequest(
                url=entry.url, folder=folder,
                name_prefix=f"{entry.index:0{width}d} - ", **common,
            )
            self.queue.add(request, entry.title)
        self.status_label.setText(tr("status_added_many", count=len(usable)))
        return True

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
        self.pause_button.setText(tr("btn_resume") if can_resume else tr("btn_pause"))
        self.pause_button.setEnabled(can_pause or can_resume)
        self.cancel_button.setEnabled(
            state in (JobState.PENDING, JobState.DOWNLOADING, JobState.PAUSED)
        )
        self.open_button.setEnabled(job is not None)
        self.pause_all_button.setEnabled(
            any(j.state in (JobState.PENDING, JobState.DOWNLOADING) for j in self.queue.jobs)
        )
        self.resume_all_button.setEnabled(
            any(j.state is JobState.PAUSED for j in self.queue.jobs)
        )

        # A hint when the queue is empty, and a count in the tab's title
        self.empty_label.setVisible(len(self.queue.jobs) == 0)
        unfinished = sum(
            1 for j in self.queue.jobs
            if j.state in (JobState.PENDING, JobState.DOWNLOADING, JobState.PAUSED)
        )
        title = tr("tab_queue_count", count=unfinished) if unfinished else tr("tab_queue")
        self.tabs.setTabText(TAB_QUEUE, title)

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

    def on_pause_all_clicked(self):
        jobs = list(self.queue.jobs)
        # Waiting jobs FIRST. Otherwise, the moment a running job pauses and frees its
        # slot, a waiting job would grab it and start downloading.
        for job in jobs:
            if job.state is JobState.PENDING:
                self.queue.pause(job)
        for job in jobs:
            if job.state is JobState.DOWNLOADING:
                self.queue.pause(job)

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
            self.status_label.setText(tr("status_queue_save_failed", error=e))

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
            self.status_label.setText(tr("status_restored", count=count))

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
        tip = ""
        if job.state is JobState.FAILED:
            tip = error_text(job.error) if job.error else job.message
        self.table.item(row, 1).setToolTip(tip)
        self.table.cellWidget(row, 5).setValue(int(self.job_percent(job)))

    def rebuild_table(self):
        self.table.setRowCount(0)
        for job in list(self.queue.jobs):
            self.update_row(job)
        self.update_buttons()

    @staticmethod
    def status_text(job):
        if job.state is JobState.DONE and job.reused:
            return tr("state_done_reused")
        if job.state is not JobState.DOWNLOADING:
            return tr(STATE_KEYS[job.state])

        p = job.progress
        if p is None:
            return tr("state_starting")
        if p.status == "processing":
            return tr("state_processing")
        if job.item_count > 1 and p.item_index:        # an older playlist-as-one-job
            return tr("state_item", current=item_position(job, p), total=job.item_count)
        return tr("state_downloading")

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
            name_prefix=job.request.name_prefix,
        )
        try:
            self.history.add(entry)
        except HistoryError as e:
            self.status_label.setText(tr("status_history_save_failed", error=e))
        self.refresh_history_table()

    def refresh_history_table(self):
        self.history_entries = self.history.load()          # newest first
        self.history_table.setRowCount(len(self.history_entries))

        for row, entry in enumerate(self.history_entries):
            if entry.mode == "audio":
                quality = tr("quality_mp3")
            elif entry.max_height:
                quality = tr("quality_upto", height=entry.max_height)
            else:
                quality = tr("quality_best_short")
            kind = tr("kind_audio" if entry.mode == "audio" else "kind_video")
            if entry.playlist:
                kind += "  •  " + tr("kind_playlist")
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
            name_prefix=entry.name_prefix,
        )
        item_count = len(items) if items else (entry.file_count if entry.playlist else 1)
        self.queue.add(request, entry.title, item_count=item_count)
        self.tabs.setCurrentIndex(TAB_QUEUE)       # jump to the progress
        self.status_label.setText(tr("status_added"))

    def on_history_clear_clicked(self):
        if not self.ask(tr("confirm_clear_history")):
            return
        try:
            self.history.clear()
        except HistoryError as e:
            self.warn(str(e))
        self.refresh_history_table()

    # ============================================================
    # Tools check and yt-dlp updates
    # ============================================================
    def check_tools(self):
        """Show a warning banner (with a Download button) if a tool is missing."""
        problems = []
        if not find_tool("ffmpeg"):
            problems.append(tr("tools_ffmpeg_missing"))
        if not find_tool("deno"):
            problems.append(tr("tools_deno_missing"))
        self.tools_label.setText("\n".join(problems))
        self.tools_label.setVisible(bool(problems))
        self.tools_button.setVisible(bool(problems))
        self.refresh_tools_status()

    def refresh_tools_status(self):
        for name, label in (("ffmpeg", self.ffmpeg_status), ("deno", self.deno_status)):
            path = find_tool(name)
            label.setText(f"✔  {path}" if path else f"✖  {tr('tool_missing')}")
        self.tools_button.setEnabled(not self.tools_busy)
        self.tools_download_button.setEnabled(bool(missing_tools()) and not self.tools_busy)

    def on_download_tools_clicked(self):
        names = missing_tools()
        if self.tools_busy or not names:
            return
        self.tools_busy = True
        self.refresh_tools_status()

        # In the background: it downloads tens of megabytes
        worker = Worker(install_tools, self.tools_folder, names, with_progress=True)
        worker.signals.progress.connect(self.on_tools_progress)
        worker.signals.finished.connect(self.on_tools_installed)
        worker.signals.failed.connect(self.on_tools_failed)
        self.tools_worker = worker
        self.pool.start(worker)

    def on_tools_progress(self, progress):
        self.status_label.setText(tr(
            "status_tools_downloading",
            tool=TOOL_LABELS[progress.tool], percent=int(progress.fraction * 100),
        ))

    def on_tools_installed(self, installed):
        self.tools_busy = False
        add_to_path(self.tools_folder)         # the programs we start (yt-dlp) will find them too
        self.downloader.refresh_tools()        # look for FFmpeg again
        self.check_tools()
        self.status_label.setText(tr("status_tools_done"))

    def on_tools_failed(self, error):
        self.tools_busy = False
        self.refresh_tools_status()
        text = error_text(error)
        self.status_label.setText(tr("status_tools_failed", error=text))
        self.warn(text)
        
    def on_update_clicked(self):
        self.update_button.setEnabled(False)
        self.status_label.setText(tr("status_checking_updates"))

        worker = Worker(latest_version)          # runs in the background: it uses the internet
        worker.signals.finished.connect(self.on_update_checked)
        self.update_worker = worker              # keep a reference
        self.pool.start(worker)

    def on_update_checked(self, latest):
        self.update_button.setEnabled(True)
        current = installed_version()

        if latest is None:
            self.status_label.setText(tr("status_update_failed"))
            return
        if not is_newer(latest, current):
            self.status_label.setText(tr("status_up_to_date", version=current))
            return

        how = tr("update_how_exe") if getattr(sys, "frozen", False) else tr("update_how_source")
        self.inform(tr("update_message", latest=latest, current=current, how=how))
        self.status_label.setText(tr("status_update_available", version=latest))

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
        title = tr("notif_finished") if still_busy else tr("notif_all_finished")
        self.tray.showMessage(title, job.title, QSystemTrayIcon.MessageIcon.Information, 6000)

    def closeEvent(self, event):
        """Qt calls this when the window is closing: save its size and position."""
        self.settings.setValue("window/geometry", self.saveGeometry())
        if self.tray is not None:
            self.tray.hide()                  # so no ghost icon stays behind
        super().closeEvent(event)