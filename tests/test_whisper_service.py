"""Tests for the Whisper transcription service."""
import sys
import types
import unittest
from unittest.mock import patch

from src.services.whisper.errors import TranscriptionError, WhisperConfigError
from src.services.whisper.service import WhisperService, _load_model


class _Segment:
    def __init__(self, start: float, end: float, text: str):
        self.start = start
        self.end = end
        self.text = text


class _Info:
    def __init__(self, language: str = "en", duration: float | None = 2.75):
        self.language = language
        self.duration = duration


class WhisperServiceSyncTests(unittest.TestCase):
    def setUp(self):
        _load_model.cache_clear()

    def tearDown(self):
        _load_model.cache_clear()

    def test_transcribe_sync_returns_structured_result(self):
        class FakeModel:
            def transcribe(self, path, language=None, initial_prompt=None, beam_size=None):
                self.path = path
                self.language = language
                self.initial_prompt = initial_prompt
                self.beam_size = beam_size
                return iter([
                    _Segment(0.0, 1.2349, " hello "),
                    _Segment(1.2351, 2.75, "world "),
                ]), _Info(language="en", duration=2.75)

        service = WhisperService(model="base", device="cpu", compute_type="int8", beam_size=7)
        fake_model = FakeModel()

        with patch("src.services.whisper.service._load_model", return_value=fake_model) as load_model:
            result = service._transcribe_sync(
                b"fake-audio",
                filename="clip.mp3",
                language="en",
                prompt="meeting notes",
            )

        load_model.assert_called_once_with("base", "cpu", "int8")
        self.assertEqual(result["text"], "hello world")
        self.assertEqual(result["language"], "en")
        self.assertEqual(result["duration_seconds"], 2.75)
        self.assertEqual(result["model"], "base")
        self.assertEqual(
            result["segments"],
            [
                {"start": 0.0, "end": 1.235, "text": "hello"},
                {"start": 1.235, "end": 2.75, "text": "world"},
            ],
        )
        self.assertEqual(fake_model.language, "en")
        self.assertEqual(fake_model.initial_prompt, "meeting notes")
        self.assertEqual(fake_model.beam_size, 7)
        self.assertTrue(fake_model.path.endswith(".mp3"))

    def test_transcribe_sync_raises_transcription_error_for_model_failure(self):
        class BrokenModel:
            def transcribe(self, *_args, **_kwargs):
                raise RuntimeError("decode failed")

        service = WhisperService()
        with patch("src.services.whisper.service._load_model", return_value=BrokenModel()):
            with self.assertRaises(TranscriptionError) as raised:
                service._transcribe_sync(b"fake-audio")

        self.assertIn("decode failed", str(raised.exception))

    def test_load_model_raises_config_error_when_dependency_missing(self):
        original = sys.modules.pop("faster_whisper", None)
        service_module = sys.modules["src.services.whisper.service"]

        def raising_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "faster_whisper":
                raise ImportError("missing")
            return original_import(name, globals, locals, fromlist, level)

        original_import = service_module.__builtins__["__import__"]

        try:
            with patch.dict(sys.modules, {}, clear=False):
                with patch.object(service_module, "__builtins__", dict(service_module.__builtins__, __import__=raising_import)):
                    with self.assertRaises(WhisperConfigError) as raised:
                        _load_model("base", "cpu", "int8")
        finally:
            if original is not None:
                sys.modules["faster_whisper"] = original
            _load_model.cache_clear()

        self.assertIn("faster-whisper", str(raised.exception))

    def test_load_model_normalizes_auto_settings(self):
        init_calls = []

        class FakeWhisperModel:
            def __init__(self, model_name, device=None, compute_type=None):
                init_calls.append((model_name, device, compute_type))

        fake_module = types.SimpleNamespace(WhisperModel=FakeWhisperModel)

        with patch.dict(sys.modules, {"faster_whisper": fake_module}):
            model = _load_model("base", "auto", "auto")

        self.assertIsInstance(model, FakeWhisperModel)
        self.assertEqual(init_calls, [("base", "cuda", "float16")])


class WhisperServiceAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_transcribe_rejects_empty_audio(self):
        service = WhisperService()
        with self.assertRaises(TranscriptionError) as raised:
            await service.transcribe(b"")

        self.assertEqual(str(raised.exception), "Audio payload is empty")

    async def test_transcribe_uses_thread_wrapper(self):
        service = WhisperService()

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch("src.services.whisper.service.asyncio.to_thread", side_effect=fake_to_thread):
            with patch.object(service, "_transcribe_sync", return_value={"text": "ok", "model": "base"}) as sync_call:
                result = await service.transcribe(b"bytes", filename="a.wav", language="en", prompt="p")

        self.assertEqual(result, {"text": "ok", "model": "base"})
        sync_call.assert_called_once_with(b"bytes", filename="a.wav", language="en", prompt="p")


if __name__ == "__main__":
    unittest.main()
