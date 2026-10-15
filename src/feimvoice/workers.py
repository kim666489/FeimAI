"""Qt workers for microphone capture, wake-word monitoring, and TTS playback."""

from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from .stt import listen_once, matches_wake_word
from .tts import speak_text


class VoiceCaptureWorker(QThread):
    recognized = pyqtSignal(str)
    status = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, config: dict[str, Any]):
        super().__init__()
        self.config = config

    def run(self) -> None:
        try:
            self.status.emit("Listening...")
            text = listen_once(self.config["stt"])
            if text:
                self.recognized.emit(text)
            else:
                self.status.emit("No speech recognized.")
        except Exception as exc:
            self.failed.emit(str(exc))


class WakeWordWorker(QThread):
    recognized = pyqtSignal(str)
    status = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, config: dict[str, Any]):
        super().__init__()
        self.config = config
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        stt = self.config["stt"]
        wake = self.config["wake"]
        try:
            while not self._stop_requested:
                self.status.emit("Waiting for FeimVoice wake word...")
                text = listen_once(
                    stt,
                    timeout=min(float(stt.get("timeout", 5)), 2.0),
                    phrase_time_limit=float(wake.get("phrase_time_limit", 3)),
                )
                if self._stop_requested:
                    break
                if not text or not matches_wake_word(text, wake.get("words", [])):
                    continue

                self.status.emit("Wake word detected. Listening for command...")
                speak_text(str(wake.get("response", "")), self.config["tts"])
                if self._stop_requested:
                    break
                command = listen_once(
                    stt,
                    timeout=float(wake.get("command_timeout", 7)),
                    phrase_time_limit=float(stt.get("phrase_time_limit", 10)),
                )
                if command:
                    self.recognized.emit(command)
                    return
        except Exception as exc:
            self.failed.emit(str(exc))


class SpeechWorker(QThread):
    status = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, text: str, config: dict[str, Any]):
        super().__init__()
        self.text = text
        self.config = config

    def run(self) -> None:
        try:
            self.status.emit("Speaking...")
            speak_text(self.text, self.config["tts"])
        except Exception as exc:
            self.failed.emit(str(exc))
