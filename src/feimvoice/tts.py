"""Text-to-speech adapters copied and isolated from MyAkane's voice system."""

from html import escape
from pathlib import Path
from typing import Any
import tempfile


def _speak_sapi(text: str, config: dict[str, Any]) -> None:
    try:
        import pyttsx3
    except ImportError as exc:
        raise RuntimeError(
            "FeimVoice SAPI TTS is not installed. Install the packages in requirements-voice.txt."
        ) from exc

    engine = pyttsx3.init()
    try:
        voice_id = str(config.get("voice_id") or "").strip()
        if voice_id:
            voices = engine.getProperty("voices")
            selected = next(
                (voice for voice in voices if voice_id.casefold() in
                 f"{voice.id} {voice.name}".casefold()), None)
            if selected is None:
                available = ", ".join(voice.name for voice in voices)
                raise ValueError(f"Voice '{voice_id}' not found. Available voices: {available}")
            engine.setProperty("voice", selected.id)
        engine.setProperty("rate", int(config.get("rate", 170)))
        engine.setProperty("volume", max(0.0, min(1.0, float(config.get("volume", 0.8)))))
        pitch = int(config.get("pitch", 0))
        if not -10 <= pitch <= 10:
            raise ValueError("FeimVoice SAPI pitch must be between -10 and 10.")
        if pitch == 0:
            engine.say(text)
            engine.runAndWait()
            return
        sapi_voice = getattr(engine.proxy._driver, "_tts", None)
        if sapi_voice is None:
            raise RuntimeError("FeimVoice pitch adjustment requires the Windows SAPI5 driver.")
        sapi_voice.Speak(f'<pitch middle="{pitch}">{escape(text)}</pitch>', 0)
        sapi_voice.WaitUntilDone(-1)
    finally:
        engine.stop()


def _speak_thai_model(text: str, config: dict[str, Any]) -> None:
    try:
        from pythaitts import TTS
    except ImportError as exc:
        raise RuntimeError(
            "FeimVoice Thai TTS is not installed. Install the packages in requirements-voice.txt."
        ) from exc

    from pydub import AudioSegment
    import winsound

    with tempfile.TemporaryDirectory(prefix="feimvoice-") as temp_dir:
        output = Path(temp_dir) / "speech.wav"
        tts = TTS(pretrained=str(config.get("thai_model", "vachana")))
        tts.tts(
            text,
            speaker_idx=str(config.get("thai_speaker", "th_f_1")),
            filename=str(output),
            speed=float(config.get("thai_rate", 1.0)),
        )
        audio = AudioSegment.from_wav(str(output))
        pitch = float(config.get("thai_pitch", 0.0))
        if pitch:
            frame_rate = int(audio.frame_rate * (2 ** (pitch / 12.0)))
            audio = audio._spawn(audio.raw_data, overrides={"frame_rate": frame_rate})
            audio = audio.set_frame_rate(44100)
        volume_db = float(config.get("thai_volume_db", 0.0))
        if volume_db:
            audio = audio + volume_db
        adjusted = Path(temp_dir) / "speech-adjusted.wav"
        audio.export(str(adjusted), format="wav")
        winsound.PlaySound(str(adjusted), winsound.SND_FILENAME)


def speak_text(text: str, config: dict[str, Any]) -> None:
    if not text or not text.strip():
        return
    if not config.get("enabled", True):
        return
    engine = str(config.get("engine", "sapi")).casefold()
    if engine == "sapi":
        _speak_sapi(text, config)
    elif engine == "pythaitts":
        _speak_thai_model(text, config)
    else:
        raise ValueError(f"Unsupported FeimVoice TTS engine: {engine}")
