from threading import Event

from conftest import wait_for

from app.config import VoiceConfig
from services.asr_service import ASRService
from services.audio_service import AudioService
from services.tts_service import TTSService


def test_record_recognize_cleanup(qt_core, tmp_path, monkeypatch):
    from services.voice_recorder_service import VoiceRecorderService

    cfg = VoiceConfig(asr_provider="online")
    audio = AudioService(cfg)
    path = tmp_path / "voice.wav"

    def record(self, stop, cancel, device=None):
        path.write_bytes(b"fake")
        stop.wait(1)
        return str(path)

    monkeypatch.setattr(VoiceRecorderService, "record", record)
    monkeypatch.setattr(ASRService, "transcribe", lambda self, file, cancel: "识别成功")
    results = []
    audio.recognized.connect(results.append)
    try:
        audio.record()
        assert audio.state == "recording"
        audio.finish_recording()
        wait_for(qt_core, lambda: bool(results) and audio.state == "idle")
        assert results == ["识别成功"]
        assert not path.exists()
    finally:
        audio.shutdown()


def test_canceled_audio_drops_old_text(qt_core, tmp_path, monkeypatch):
    from services.voice_recorder_service import VoiceRecorderService

    cfg = VoiceConfig(asr_provider="online")
    audio = AudioService(cfg)
    started = Event()

    def record(self, stop, cancel, device=None):
        started.set()
        cancel.wait(1)
        return ""

    monkeypatch.setattr(VoiceRecorderService, "record", record)
    results = []
    audio.recognized.connect(results.append)
    try:
        audio.record()
        assert started.wait(1)
        audio.stop()
        audio.shutdown()
        qt_core.processEvents()
        assert results == []
        assert audio.state == "idle"
    finally:
        audio.shutdown()


def test_edge_failure_uses_system(monkeypatch):
    service = TTSService(VoiceConfig())
    calls = []

    async def fail(text, cancel):
        raise ValueError("provider unavailable")

    monkeypatch.setattr(service, "_edge", fail)
    monkeypatch.setattr(service, "_system", lambda text, cancel: calls.append(text))
    service.speak("hello", Event())
    assert calls == ["hello"]


def test_asr_auto_falls_back(tmp_path, monkeypatch):
    source = tmp_path / "fake.wav"
    source.write_bytes(b"fake")
    service = ASRService(VoiceConfig(asr_provider="auto"))

    async def fail(path, cancel):
        raise OSError("offline")

    monkeypatch.setattr(service, "_online", fail)
    monkeypatch.setattr(service, "_offline", lambda path, cancel: "offline text")
    assert service.transcribe(str(source)) == "offline text"
