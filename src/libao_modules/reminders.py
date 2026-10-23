"""A single deadline timer, armed only when explicitly enabled."""
import math
import time


class ReminderController:
    def __init__(self, store, call_later, cancel, notify, clock=time.time):
        self.store, self.call_later, self.cancel = store, call_later, cancel
        self.notify, self.clock = notify, clock
        self.enabled = False
        self.quiet = False
        self.closed = False
        self.token = None
        self.last_error = None

    def set_enabled(self, enabled):
        if self.closed:
            return
        self.enabled = bool(enabled)
        self.refresh()

    def set_quiet(self, quiet):
        if self.closed:
            return
        self.quiet = bool(quiet)
        self.refresh()

    def _cancel(self):
        if self.token is not None:
            self.cancel(self.token)
            self.token = None

    def refresh(self):
        """Call on edits, host resume/time-change, and opening the tools."""
        self._cancel()
        if self.closed or not self.enabled:
            return
        if not self.quiet:
            self._deliver(self.store.take_queued())
        self._arm()

    def _arm(self):
        # A host notification may run a nested Tk event loop. Recheck state
        # after it returns and replace any timer installed by that callback.
        self._cancel()
        if self.closed or not self.enabled:
            return
        deadline = self.store.next_due()
        if deadline is not None:
            milliseconds = max(0, math.ceil((deadline - self.clock()) * 1000))
            # Tcl's deadline integer has a practical bound. Very distant reminders
            # re-arm at this limit (~24.8 days), rather than second/minute polling.
            self.token = self.call_later(min(milliseconds, 2_147_483_647), self._fire)

    def _deliver(self, rows):
        if not rows:
            return
        try:
            self.notify(rows)
            self.last_error = None
        except Exception as error:
            self.store.requeue(rows)
            self.last_error = str(error)
            # No rapid automatic retries. Retry on the next explicit refresh.

    def _fire(self):
        self.token = None
        if self.closed or not self.enabled:
            return
        rows = self.store.take_due(self.clock(), quiet=self.quiet)
        if not self.quiet:
            self._deliver(rows)
        self._arm()

    def close(self):
        self._cancel()
        self.enabled = False
        self.closed = True
