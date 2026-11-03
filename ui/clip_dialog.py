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
from .parsing import parse_time
from .range_slider import RangeSlider


class ClipDialog(QDialog):
    """Pick the part of a video to download: drag the two handles, or type the times."""

    def __init__(self, duration, start=None, end=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose the part to download")
        self.resize(580, 270)
        self.duration = int(duration)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.addWidget(QLabel(f"Video length: {format_duration(self.duration)}"))

        self.slider = RangeSlider(self.duration, start or 0, end)
        layout.addWidget(self.slider)

        times_row = QHBoxLayout()
        self.from_edit = QLineEdit()
        self.to_edit = QLineEdit()
        times_row.addWidget(QLabel("From"))
        times_row.addWidget(self.from_edit)
        times_row.addWidget(QLabel("To"))
        times_row.addWidget(self.to_edit)
        layout.addLayout(times_row)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("muted")
        layout.addWidget(self.summary_label)

        whole_button = QPushButton("Use the whole video")
        whole_button.clicked.connect(self.use_whole_video)
        layout.addWidget(whole_button)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
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
        self.summary_label.setText(
            f"Selected: {format_duration(start)} → {format_duration(end)}"
            f"   ({format_duration(end - start)} long)"
        )

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

    def selected_range(self):
        """(start, end) in seconds. end is None for "until the end".
        (None, None) means the whole video."""
        start, end = self.slider.start, self.slider.end
        if end >= self.duration:
            end = None
        if start == 0 and end is None:
            return None, None
        return float(start), (float(end) if end is not None else None)