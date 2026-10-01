"""Always-on, local voice loop: wake word, VAD, STT, agent, then TTS."""

import logging
import re
import threading
import time
import unicodedata
from collections import deque

from app.core import config

log = logging.getLogger("jarvis.voice")


class VoiceService:
    SAMPLE_RATE = 16_000
    WAKE_FRAME_SAMPLES = 1_280  # openWakeWord works on 80 ms frames at 16 kHz.
    VAD_FRAME_BYTES = 960  # 30 ms, mono, signed 16-bit PCM.

    def __init__(self):
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._wake_model = None
        self._stt_model = None
        self._tts_engine = None
        self._last_transcript = ""
        self._last_transcript_at = 0.0
        self._status = {
            "enabled": bool(config.VOICE_ENABLED),
            "phase": "stopped",
            "wake_word": config.VOICE_WAKE_WORD.replace("_", " "),
            "last_heard": "",
            "last_reply": "",
            "last_error": "",
        }

    def _set_status(self, **values) -> None:
        with self._lock:
            self._status.update(values)

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def start(self) -> None:
        if not config.VOICE_ENABLED:
            self._set_status(enabled=False, phase="disabled")
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._status.update(enabled=True, phase="starting", last_error="")
            self._thread = threading.Thread(target=self._run, name="jarvis-voice", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            # Python cannot interrupt a third-party model import. Keep API and
            # shutdown callers responsive while that import unwinds.
            thread.join(timeout=2)
        if thread is not None and thread.is_alive():
            self._set_status(phase="stopping", enabled=False)
        else:
            self._thread = None
            self._set_status(phase="stopped", enabled=False)

    def _load_models(self) -> None:
        if self._wake_model is None:
            from openwakeword.model import Model
            from openwakeword.utils import download_models

            download_models(model_names=[config.VOICE_WAKE_WORD])
            self._wake_model = Model(
                wakeword_models=[config.VOICE_WAKE_WORD],
                inference_framework="onnx",
                vad_threshold=0.5,
            )
        if self._stt_model is None:
            from faster_whisper import WhisperModel

            self._stt_model = WhisperModel(
                config.VOICE_STT_MODEL,
                device="cpu",
                compute_type="int8",
                cpu_threads=max(1, config.VOICE_STT_CPU_THREADS),
                num_workers=1,
            )

    def _run(self) -> None:
        retry_delay = 1.0
        try:
            while not self._stop.is_set():
                try:
                    self._set_status(phase="starting", last_error="", enabled=True)
                    self._load_models()
                    if self._stop.is_set():
                        break
                    self._listen()
                    retry_delay = 1.0
                except Exception as exc:
                    log.exception("Voice listener failed; it will retry")
                    self._set_status(phase="recovering", last_error=str(exc)[:300], enabled=True)
                    self._stop.wait(retry_delay)
                    retry_delay = min(retry_delay * 2, 20.0)
        finally:
            if self._stop.is_set():
                self._set_status(phase="stopped", enabled=False)
            else:
                self._set_status(phase="stopped", enabled=False)

    def _listen(self) -> None:
        import numpy as np
        import sounddevice as sd
        import webrtcvad

        device = config.VOICE_INPUT_DEVICE.strip() or None
        if device and device.isdigit():
            device = int(device)
        vad = webrtcvad.Vad(max(0, min(3, config.VOICE_VAD_MODE)))
        try:
            with sd.RawInputStream(
                samplerate=self.SAMPLE_RATE,
                blocksize=self.WAKE_FRAME_SAMPLES,
                device=device,
                channels=1,
                dtype="int16",
            ) as stream:
                self._set_status(phase="wake-word listening", last_error="", enabled=True)
                while not self._stop.is_set():
                    block, _overflowed = stream.read(self.WAKE_FRAME_SAMPLES)
                    if _overflowed:
                        log.info("Microphone input overflow; dropping the partial wake frame")
                        self._wake_model.reset()
                        continue
                    frame = np.frombuffer(block, dtype=np.int16)
                    scores = self._wake_model.predict(frame)
                    score = max((float(value) for value in scores.values()), default=0.0)
                    if score < config.VOICE_WAKE_THRESHOLD:
                        continue

                    log.info("Wake word detected (score %.2f)", score)
                    self._wake_model.reset()
                    self._set_status(phase="waiting for command")
                    audio = self._capture_command(stream, vad)
                    if self._stop.is_set():
                        break
                    if not audio:
                        self._set_status(phase="wake-word listening")
                        continue

                    self._set_status(phase="transcribing")
                    try:
                        transcript = self._transcribe(audio, np)
                    except Exception as exc:
                        log.warning("Speech transcription failed; listener remains active: %s", exc)
                        self._set_status(phase="wake-word listening", last_error=f"Speech transcription failed: {exc}"[:300])
                        continue
                    if not self._is_new_transcript(transcript):
                        self._set_status(phase="wake-word listening")
                        continue
                    self._set_status(last_heard=transcript)
                    if not transcript:
                        self._set_status(phase="wake-word listening")
                        continue

                    self._set_status(phase="thinking")
                    try:
                        from app.tasks import task_manager

                        _task_id, reply = task_manager.run_sync(transcript)
                    except Exception as exc:
                        log.exception("Voice command failed in the agent")
                        reply = "I couldn't complete that request. Please try again."
                    self._set_status(last_reply=reply, phase="speaking")
                    self._speak(reply)
                    self._set_status(phase="wake-word listening")
        except Exception as exc:
            log.warning("Microphone input is unavailable; voice listener will retry: %s", exc)
            self._set_status(phase="recovering", enabled=True, last_error=f"Microphone unavailable: {exc}"[:300])
            raise

    def _capture_command(self, stream, vad) -> bytes:
        frame_buffer = bytearray()
        pre_roll: deque[bytes] = deque(maxlen=8)
        audio_frames: list[bytes] = []
        speech_run = 0
        speech_started = False
        last_speech_at = time.monotonic()
        started_at = time.monotonic()
        end_silence = max(0.3, config.VOICE_END_SILENCE_MS / 1000)
        no_speech_timeout = max(1, config.VOICE_NO_SPEECH_TIMEOUT_SECONDS)
        max_duration = max(2, config.VOICE_MAX_COMMAND_SECONDS)

        while not self._stop.is_set():
            block, _overflowed = stream.read(self.WAKE_FRAME_SAMPLES)
            frame_buffer.extend(block)
            while len(frame_buffer) >= self.VAD_FRAME_BYTES:
                frame = bytes(frame_buffer[:self.VAD_FRAME_BYTES])
                del frame_buffer[:self.VAD_FRAME_BYTES]
                voiced = vad.is_speech(frame, self.SAMPLE_RATE)
                now = time.monotonic()
                if not speech_started:
                    pre_roll.append(frame)
                    speech_run = speech_run + 1 if voiced else 0
                    if speech_run >= 2:
                        speech_started = True
                        audio_frames.extend(pre_roll)
                        last_speech_at = now
                else:
                    audio_frames.append(frame)
                    if voiced:
                        last_speech_at = now
                    elif now - last_speech_at >= end_silence:
                        return b"".join(audio_frames)

                if speech_started and now - started_at >= max_duration:
                    return b"".join(audio_frames)
                if not speech_started and now - started_at >= no_speech_timeout:
                    return b""
        return b""

    def _transcribe(self, pcm: bytes, np) -> str:
        if not pcm:
            return ""
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = self._stt_model.transcribe(
            samples,
            beam_size=3,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        return " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()

    def _is_new_transcript(self, transcript: str, now: float | None = None) -> bool:
        normalized = " ".join(unicodedata.normalize("NFKC", transcript).lower().split())
        if not normalized:
            return False
        now = time.monotonic() if now is None else now
        duplicate = normalized == self._last_transcript and now - self._last_transcript_at < 2.5
        if duplicate:
            return False
        self._last_transcript = normalized
        self._last_transcript_at = now
        return True

    @staticmethod
    def _speech_text(text: str) -> str:
        """Avoid speaking JSON, code blocks, or accidental tool-call payloads."""
        cleaned = re.sub(r"```.*?```", " ", text, flags=re.S)
        cleaned = re.sub(r"\{\s*['\"]?(?:name|tool_calls|function)['\"]?\s*:.*?\}", " ", cleaned, flags=re.S)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned[:3000]

    def _speak(self, text: str) -> None:
        text = self._speech_text(text)
        if not text:
            return
        try:
            if self._tts_engine is None:
                import pyttsx3

                self._tts_engine = pyttsx3.init("sapi5")
                self._tts_engine.setProperty("rate", config.VOICE_TTS_RATE)
            self._tts_engine.say(text)
            self._tts_engine.runAndWait()
        except Exception as exc:
            log.warning("Offline speech output is unavailable: %s", exc)
            self._tts_engine = None
            self._set_status(last_error=f"Speech output unavailable: {exc}"[:300])


voice_service = VoiceService()
