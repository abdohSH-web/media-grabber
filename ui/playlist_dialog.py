from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from .formatting import format_duration
from .i18n import tr


class PlaylistDialog(QDialog):
    """A pop-up window with one checkbox per video of the playlist."""

    def __init__(self, entries, selected=None, parent=None):
        """entries : tuple of PlaylistEntry
        selected   : tuple of positions that start checked (None = all of them)"""
        super().__init__(parent)
        self.setWindowTitle(tr("dlg_choose_videos"))
        self.resize(600, 620)

        layout = QVBoxLayout(self)
        self.counter_label = QLabel()
        layout.addWidget(self.counter_label)

        self.list_widget = QListWidget()
        for entry in entries:
            text = f"{entry.index}.  {entry.title}"
            if entry.duration_seconds:
                text += f"   ({format_duration(entry.duration_seconds)})"

            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            is_checked = selected is None or entry.index in selected
            item.setCheckState(Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, entry.index)   # the position, hidden inside
            self.list_widget.addItem(item)

        self.list_widget.itemChanged.connect(self.update_counter)
        layout.addWidget(self.list_widget, stretch=1)

        quick_row = QHBoxLayout()
        select_all = QPushButton(tr("btn_select_all"))
        select_all.clicked.connect(lambda: self.set_all(Qt.CheckState.Checked))
        select_none = QPushButton(tr("btn_select_none"))
        select_none.clicked.connect(lambda: self.set_all(Qt.CheckState.Unchecked))
        quick_row.addWidget(select_all)
        quick_row.addWidget(select_none)
        quick_row.addStretch()
        layout.addLayout(quick_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("btn_ok"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("btn_cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.update_counter()

    def set_all(self, state):
        for row in range(self.list_widget.count()):
            self.list_widget.item(row).setCheckState(state)

    def selected_indices(self):
        """The playlist positions of the checked videos, as a tuple of numbers."""
        chosen = []
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                chosen.append(item.data(Qt.ItemDataRole.UserRole))
        return tuple(chosen)

    def update_counter(self, *_):
        self.counter_label.setText(tr(
            "plist_counter", chosen=len(self.selected_indices()), total=self.list_widget.count()
        ))