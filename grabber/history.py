import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .errors import HistoryError


@dataclass(frozen=True)
class HistoryEntry:
    """One finished download, as it is saved in the history file."""
    title: str
    url: str
    mode: str                  # "video" or "audio"
    max_height: int | None
    playlist: bool
    folder: str
    finished_at: str           # ISO text, e.g. "2026-11-01T14:30:05"
    file_count: int
    items: list[int] | None = None   # chosen playlist positions (None = the whole playlist)


class HistoryStore:
    """Keeps the history in a small JSON file."""

    MAX_ENTRIES = 500          # older entries are dropped

    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        """All entries, NEWEST first."""
        return list(reversed(self._read_all()))

    def add(self, entry):
        entries = self._read_all()
        entries.append(entry)
        self._write_all(entries[-self.MAX_ENTRIES:])

    def clear(self):
        self._write_all([])

    # ------------------------------------------------------------
    # Internals. The file stores entries OLDEST first.
    # ------------------------------------------------------------
    def _read_all(self):
        if not self.path.exists():
            return []                          # no file yet = no history yet
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return [HistoryEntry(**item) for item in raw]
        except (OSError, ValueError, TypeError):
            # Unreadable or the wrong shape. Never crash the app because of history:
            # keep a copy of the bad file and start fresh.
            self._backup_bad_file()
            return []

    def _write_all(self, entries):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            data = [asdict(entry) for entry in entries]
            temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            # os.replace swaps the files in one step, so history.json is never
            # left half-written, even if the program is killed at that moment
            os.replace(temp, self.path)
        except OSError as e:
            raise HistoryError(f"Could not write {self.path}: {e}") from e

    def _backup_bad_file(self):
        try:
            self.path.replace(self.path.with_suffix(".bak"))
        except OSError:
            pass