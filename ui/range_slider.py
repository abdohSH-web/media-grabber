from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import theme


class RangeSlider(QWidget):
    """A slider with TWO handles. It selects a range, like the trimmer of a video editor.
    Qt has no such widget, so we draw it ourselves (paintEvent) and handle the mouse."""

    rangeChanged = Signal(int, int)     # start, end (whole seconds)

    MARGIN = 14      # space at both ends, so the handles aren't cut off
    HANDLE = 9       # handle radius in pixels

    def __init__(self, duration, start=0, end=None, parent=None):
        super().__init__(parent)
        self.duration = max(int(duration), 1)
        self.start = int(start)
        self.end = int(end) if end is not None else self.duration
        self._dragging = None            # "start", "end" or None
        self.setMinimumHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_range(self, start, end):
        """Set both handles. Values are clamped, so the range is always valid."""
        start = max(0, min(int(start), self.duration - 1))
        end = max(start + 1, min(int(end), self.duration))
        if (start, end) != (self.start, self.end):
            self.start, self.end = start, end
            self.update()                # ask Qt to repaint the widget
            self.rangeChanged.emit(start, end)

    # ---------- converting between seconds and pixels ----------
    def _x_of(self, seconds):
        width = max(self.width() - 2 * self.MARGIN, 1)
        return self.MARGIN + seconds / self.duration * width

    def _seconds_at(self, x):
        width = max(self.width() - 2 * self.MARGIN, 1)
        fraction = (x - self.MARGIN) / width
        return round(max(0.0, min(fraction, 1.0)) * self.duration)

    # ---------- drawing ----------
    def paintEvent(self, event):
        colors = theme.current_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        middle = self.height() / 2
        x1, x2 = self._x_of(self.start), self._x_of(self.end)

        # The whole track (grey)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors["border"]))
        painter.drawRoundedRect(
            QRectF(self.MARGIN, middle - 3, self.width() - 2 * self.MARGIN, 6), 3, 3
        )

        # The selected part (accent colour)
        painter.setBrush(QColor(colors["accent"]))
        painter.drawRoundedRect(QRectF(x1, middle - 3, x2 - x1, 6), 3, 3)

        # The two handles: a ring in the accent colour
        painter.setPen(QPen(QColor(colors["accent"]), 3))
        painter.setBrush(QColor(colors["surface"]))
        for x in (x1, x2):
            painter.drawEllipse(QPointF(x, middle), self.HANDLE, self.HANDLE)

    # ---------- the mouse ----------
    def mousePressEvent(self, event):
        x = event.position().x()
        # Grab the handle that is closer to where the user clicked
        if abs(x - self._x_of(self.start)) <= abs(x - self._x_of(self.end)):
            self._dragging = "start"
        else:
            self._dragging = "end"
        self._move_handle(x)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._move_handle(event.position().x())

    def mouseReleaseEvent(self, event):
        self._dragging = None

    def _move_handle(self, x):
        seconds = self._seconds_at(x)
        if self._dragging == "start":
            self.set_range(min(seconds, self.end - 1), self.end)
        else:
            self.set_range(self.start, max(seconds, self.start + 1))