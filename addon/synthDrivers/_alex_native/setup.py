"""Keep cancellable setup running when the user closes and reopens NVDA's settings window."""

from dataclasses import dataclass, replace
import threading
import time

from . import apple, installer


@dataclass(frozen=True)
class SetupState:
	stage: str = "Not started"
	percent: int = 0
	detail: str = "Download the required files from Apple to use Alex."
	running: bool = False
	error: bool = False


class SetupController:
	def __init__(self):
		self.state = SetupState()
		self._lock = threading.Lock()
		self._cancel = threading.Event()
		self._thread = None
		self._listeners = []
		self._last_update = 0

	def subscribe(self, listener):
		with self._lock:
			self._listeners.append(listener)
			state = self.state
		listener(state)

	def unsubscribe(self, listener):
		with self._lock:
			if listener in self._listeners:
				self._listeners.remove(listener)

	def _publish(self, state):
		with self._lock:
			self.state = state
			listeners = tuple(self._listeners)
		for listener in listeners:
			try:
				listener(state)
			except Exception:
				# Closing a settings window must not break the downloader.
				pass

	def _progress(self, stage, percent, detail):
		now = time.monotonic()
		if stage == self.state.stage and percent != 100 and now - self._last_update < 0.3:
			return
		self._last_update = now
		self._publish(SetupState(stage, max(0, min(100, percent)), detail, True))

	def start(self, root):
		if self._thread is not None and self._thread.is_alive():
			return False
		self._cancel.clear()
		self._publish(SetupState("Starting setup", running=True))
		self._thread = threading.Thread(target=self._run, args=(root,), name="Alex setup", daemon=True)
		self._thread.start()
		return True

	def _run(self, root):
		try:
			installer.install(root, self._progress, self._cancel)
		except apple.Cancelled:
			self._publish(SetupState("Cancelled", detail="Downloads are kept. Press Download and set up Alex to continue."))
		except Exception as error:
			try:
				from logHandler import log
				log.error("Alex setup failed", exc_info=True)
			except ImportError:
				pass
			self._publish(SetupState("Setup failed", detail=str(error), error=True))
		else:
			self._publish(SetupState("Ready", 100, "Alex is ready. Press Use Alex, or choose Alex in NVDA's Synthesizer dialog."))

	def cancel(self):
		self._cancel.set()
		if self.state.running:
			self._publish(replace(self.state, stage="Cancelling", detail="Waiting for the current read to stop. Partial downloads will be kept."))


controller = SetupController()
