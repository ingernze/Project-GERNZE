"""One entrance allowance owned by a desktop process, never persisted to disk."""
import threading


class EntranceSession:
    def __init__(self):
        self._lock = threading.Lock()
        self._claimed = False

    def claim(self):
        # Concurrent page loads may consume the allowance only once.
        with self._lock:
            if self._claimed:
                return False
            self._claimed = True
            return True
