import threading
from collections import deque
from datetime import datetime


class BotSessionBridge:
    """
    Bridge between bot scripts (LinkedIn / Glints) and either CLI or Web Dashboard.
    In CLI mode, uses standard print() and input().
    In Web mode, streams logs and pauses on prompts until answered via iOS/Android/macOS browser.
    """

    def __init__(self):
        self.web_mode = False
        self.running = False
        self.stop_requested = False
        self.active_portal = None
        self.logs = deque(maxlen=400)
        self.lock = threading.Lock()
        self.pending_prompt = None
        self._prompt_event = threading.Event()
        self._prompt_answer = ""

    def start_web_run(self, portal_name):
        with self.lock:
            self.web_mode = True
            self.running = True
            self.stop_requested = False
            self.active_portal = portal_name
            self.logs.clear()
            self.pending_prompt = None
            self._prompt_event.clear()
            self._prompt_answer = ""

    def finish_web_run(self):
        with self.lock:
            self.running = False
            self.active_portal = None
            self.pending_prompt = None
            self._prompt_event.set()

    def request_stop(self):
        with self.lock:
            self.stop_requested = True
            if self.pending_prompt:
                self._prompt_answer = ""
                self._prompt_event.set()

    def log(self, message):
        import sys
        text = str(message)
        sys.__stdout__.write(text + "\n")
        sys.__stdout__.flush()
        if self.web_mode:
            ts = datetime.now().strftime("%H:%M:%S")
            with self.lock:
                self.logs.append(f"[{ts}] {text}")

    def ask(self, question, options=None, kind="text"):
        """
        Ask the user for input.
        kind: 'text' | 'choice' | 'confirm'
        options: optional list of strings for 'choice'
        """
        if not self.web_mode:
            if options:
                for idx, opt in enumerate(options, 1):
                    print(f"   [{idx}] {opt}")
            return input(f" >>> {question}: ").strip()

        if self.stop_requested:
            return ""

        with self.lock:
            self.pending_prompt = {
                "question": question,
                "options": options or [],
                "kind": kind,
            }
            self._prompt_event.clear()
            self._prompt_answer = ""

        self.log(f"[INPUT DIBUTUHKAN] {question}")
        self._prompt_event.wait()

        with self.lock:
            self.pending_prompt = None
            return self._prompt_answer

    def submit_web_answer(self, answer):
        with self.lock:
            self._prompt_answer = str(answer or "").strip()
            self._prompt_event.set()


bridge = BotSessionBridge()
