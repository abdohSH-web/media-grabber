from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .formatting import format_duration
from .i18n import tr
from .parsing import parse_time
from .range_slider import RangeSlider
from .preview_dialog import PreviewDialog


class ClipDialog(QDialog):
    """Pick the part of a video to download: drag the two handles, or type the times."""

    def __init__(self, duration, start=None, end=None, parent=None, preview_url="", page_url=""):
        super().__init__(parent)
        self.setWindowTitle(tr("dlg_clip_title"))
        self.resize(580, 270)
        self.duration = int(duration)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.addWidget(QLabel(tr("clip_video_length", length=format_duration(self.duration))))

        self.slider = RangeSlider(self.duration, start or 0, end)
        layout.addWidget(self.slider)

        times_row = QHBoxLayout()
        self.from_edit = QLineEdit()
        self.to_edit = QLineEdit()
        times_row.addWidget(QLabel(tr("lbl_from")))
        times_row.addWidget(self.from_edit)
        times_row.addWidget(QLabel(tr("lbl_to")))
        times_row.addWidget(self.to_edit)
        layout.addLayout(times_row)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("muted")
        layout.addWidget(self.summary_label)

        whole_button = QPushButton(tr("btn_whole_video"))
        whole_button.clicked.connect(self.use_whole_video)
        self.preview_url = preview_url
        self.page_url = page_url
        if preview_url:                          # no stream = no button
            preview_button = QPushButton(tr("btn_preview_part"))
            preview_button.clicked.connect(self.preview_part)
            layout.addWidget(preview_button)
        layout.addWidget(whole_button)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("btn_ok"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("btn_cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # The slider and the text boxes keep each other up to date
        self.slider.rangeChanged.connect(self.show_range)
        self.from_edit.editingFinished.connect(self.on_text_edited)
        self.to_edit.editingFinished.connect(self.on_text_edited)
        self.show_range(self.slider.start, self.slider.end)

    def show_range(self, start, end):
        """Write the range in the text boxes and in the summary line."""
        self.from_edit.setText(format_duration(start))
        self.to_edit.setText(format_duration(end))
        self.summary_label.setText(tr(
            "clip_summary",
            start=format_duration(start), end=format_duration(end),
            length=format_duration(end - start),
        ))

    def on_text_edited(self):
        try:
            start = parse_time(self.from_edit.text())
            end = parse_time(self.to_edit.text())
        except ValueError:
            self.show_range(self.slider.start, self.slider.end)    # put the old values back
            return
        self.slider.set_range(start, end)                          # clamps to a valid range
        self.show_range(self.slider.start, self.slider.end)        # show what it really became

    def use_whole_video(self):
        self.slider.set_range(0, self.duration)
        self.show_range(self.slider.start, self.slider.end)

    def preview_part(self):
        """Play only the selected part, so the user sees what they are about to download."""
        PreviewDialog(
            self.preview_url, self.page_url, self.slider.start, self.slider.end, self
        ).exec()

    def selected_range(self):
        """(start, end) in seconds. end is None for "until the end".
        (None, None) means the whole video."""
        start, end = self.slider.start, self.slider.end
        if end >= self.duration:
            end = None
        if start == 0 and end is None:
            return None, None
        return float(start), (float(end) if end is not None else None)