import traceback
from urllib.request import urlopen

from PySide6.QtCore import QObject, QRunnable, Signal

from grabber.errors import GrabberError, UserCancelledError


class WorkerSignals(QObject):
    """A Worker can't emit signals itself (it isn't a QObject), so it owns this."""
    finished = Signal(object)    # carries the result
    failed = Signal(object)      # carries the ERROR OBJECT (the UI decides the wording)
    progress = Signal(object)    # carries a Progress object
    cancelled = Signal()         # the user cancelled: no message needed


class Worker(QRunnable):
    """Runs ONE function in a background thread and reports back with signals."""

    def __init__(self, function, *args, with_progress=False, **kwargs):
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs                 # extra named arguments for the function
        self.with_progress = with_progress
        self.signals = WorkerSignals()
        # We keep a reference to the worker ourselves (in the window),
        # so Qt must not delete it behind our back.
        self.setAutoDelete(False)

    def run(self):
        """Qt calls this in a background thread. NEVER touch widgets here."""
        try:
            kwargs = dict(self.kwargs)
            if self.with_progress:
                kwargs["on_progress"] = self.signals.progress.emit
            result = self.function(*self.args, **kwargs)
        except UserCancelledError:
            self.signals.cancelled.emit()        # BEFORE GrabberError: it is a subclass
        except GrabberError as e:
            self.signals.failed.emit(e)
        except Exception as e:
            # Last line of defence: a bug in a thread would otherwise vanish silently.
            traceback.print_exc()
            self.signals.failed.emit(
                GrabberError(f"Unexpected error: {e}", code="unexpected", reason=str(e))
            )
        else:
            self.signals.finished.emit(result)


def load_thumbnail(url):
    """Download the preview image. Returns the raw bytes, or None.
    The thumbnail is optional, so ANY failure just means "no preview"."""
    if not url:
        return None
    try:
        with urlopen(url, timeout=10) as response:
            return response.read()
    except Exception:
        return None


class QueueBridge(QObject):
    """The queue runs in plain Python threads and knows nothing about Qt.
    This tiny object turns its callback into a Qt signal, which Qt delivers
    safely in the main thread."""
    changed = Signal(object)