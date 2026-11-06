from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .formatting import format_duration
from .i18n import tr


class PreviewDialog(QDialog):
    """Plays a small version of the video straight from the website. Nothing is saved.
    start_seconds / end_seconds: play only that part (used by the clip window)."""

    def __init__(self, stream_url, page_url, start_seconds=None, end_seconds=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("dlg_preview_title"))
        self.resize(780, 540)
        self.page_url = page_url
        self.start_ms = int(start_seconds * 1000) if start_seconds else 0
        self.end_ms = int(end_seconds * 1000) if end_seconds else None
        self.positioned = False          # did we already jump to the start of the part?

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.video = QVideoWidget()
        self.video.setMinimumHeight(320)
        layout.addWidget(self.video, stretch=1)

        self.message = QLabel(tr("preview_loading"))
        self.message.setObjectName("muted")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        self.browser_button = QPushButton(tr("btn_open_browser"))
        self.browser_button.setVisible(False)             # only shown if the preview fails
        self.browser_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.page_url)))
        layout.addWidget(self.browser_button, alignment=Qt.AlignmentFlag.AlignLeading)

        # The controls keep the same order in Arabic too: time runs left to right
        controls = QWidget()
        controls.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        row = QHBoxLayout(controls)
        row.setContentsMargins(0, 0, 0, 0)
        self.play_button = QPushButton("⏸")
        self.play_button.setFixedWidth(52)
        self.play_button.clicked.connect(self.toggle_play)
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.sliderMoved.connect(lambda ms: self.player.setPosition(ms))
        self.time_label = QLabel("0:00 / 0:00")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setFixedWidth(90)
        self.volume_slider.valueChanged.connect(lambda value: self.audio.setVolume(value / 100))
        row.addWidget(self.play_button)
        row.addWidget(self.seek_slider, stretch=1)
        row.addWidget(self.time_label)
        row.addWidget(QLabel("🔊"))
        row.addWidget(self.volume_slider)
        layout.addWidget(controls)

        # The player: it needs somewhere to show the picture and somewhere to play the sound
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.7)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.durationChanged.connect(lambda ms: self.seek_slider.setRange(0, ms))
        self.player.positionChanged.connect(self.on_position)
        self.player.mediaStatusChanged.connect(self.on_status)
        self.player.playbackStateChanged.connect(self.on_state)
        self.player.errorOccurred.connect(self.on_error)
        self.player.setSource(QUrl(stream_url))
        self.player.play()

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def on_state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText("⏸" if playing else "▶")

    def on_position(self, ms):
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(ms)
        total = self.player.duration()
        self.time_label.setText(f"{format_duration(ms // 1000)} / {format_duration(total // 1000)}")

        # Playing only a part: stop at its end and go back to its start
        if self.end_ms is not None and ms >= self.end_ms:
            self.player.pause()
            self.player.setPosition(self.start_ms)

    def on_status(self, status):
        loaded = (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia)
        if status in loaded:
            self.message.setText("")
            if not self.positioned:               # jump to the start of the part, once
                self.positioned = True
                if self.start_ms:
                    self.player.setPosition(self.start_ms)
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.show_failure()

    def on_error(self, error, text):
        self.show_failure()

    def show_failure(self):
        self.message.setText(tr("preview_failed"))
        self.browser_button.setVisible(True)

    def done(self, result):
        """Called however the window closes (X, Esc, buttons): stop the sound first."""
        self.player.stop()
        self.player.setSource(QUrl())
        super().done(result)