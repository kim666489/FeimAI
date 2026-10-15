"""Speech-to-text adapters used by FeimVoice."""

import re
from typing import Any


def normalize_wake_word(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.casefold(), flags=re.UNICODE).strip()


def listen_once(config: dict[str, Any], timeout: float | None = None,
                phrase_time_limit: float | None = None) -> str | None:
    try:
        import speech_recognition as sr
    except ImportError as exc:
        raise RuntimeError(
            "FeimVoice STT is not installed. Install the packages in requirements-voice.txt."
        ) from exc

    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = True
    recognizer.pause_threshold = float(config.get("pause_threshold", 0.8))

    try:
        with sr.Microphone() as source:
            ambient_duration = max(0.0, float(config.get("ambient_noise_duration", 0.5)))
            if ambient_duration:
                recognizer.adjust_for_ambient_noise(source, duration=ambient_duration)
            audio = recognizer.listen(
                source,
                timeout=timeout if timeout is not None else float(config.get("timeout", 5)),
                phrase_time_limit=(phrase_time_limit if phrase_time_limit is not None
                                   else float(config.get("phrase_time_limit", 10))),
            )
    except sr.WaitTimeoutError:
        return None
    except OSError as exc:
        raise RuntimeError(f"FeimVoice could not access the microphone: {exc}") from exc

    try:
        engine = config.get("engine", "google").casefold()
        if engine == "google":
            return recognizer.recognize_google(
                audio, language=config.get("language", "th-TH")).strip() or None
        raise ValueError(f"Unsupported FeimVoice STT engine: {engine}")
    except sr.UnknownValueError:
        return None
    except sr.RequestError as exc:
        raise RuntimeError(f"Speech recognition service request failed: {exc}") from exc


def matches_wake_word(text: str, wake_words: list[str]) -> bool:
    spoken = normalize_wake_word(text)
    if not spoken:
        return False
    return any(
        normalize_wake_word(word) in spoken
        for word in wake_words
        if normalize_wake_word(word)
    )
