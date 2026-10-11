"""ナレーションの長さとシーン・字幕のタイミングのテスト。"""

import wave
from pathlib import Path

import pytest
from PIL import Image

from videomaker import voicebox as voicebox_module
from videomaker.config import AppConfig
from videomaker.models import VideoScript
from videomaker.pipeline import VideoPipeline, _line_timings
from videomaker.renderer import Renderer


def test_line_timings() -> None:
    assert _line_timings([2.0, 3.0, 1.0], margin_before=1.0, interval=0.5) == [
        (1.0, 3.0), (3.5, 6.5), (7.0, 8.0)
    ]


def test_subtitle_follows_line_timings() -> None:
    script = VideoScript.model_validate({
        "video": {},
        "scenes": [{"id": "s1", "image": "a.png", "duration": 10.0, "voiceover": "一行目\n二行目\n三行目"}],
    })
    renderer = Renderer(script, config=AppConfig(subtitle_line_interval=0.5))
    timings = [(1.0, 3.0), (3.5, 6.5), (7.0, 8.0)]
    clips = renderer._create_subtitle_clip(
        script.scenes[0], text="一行目\n二行目\n三行目", window=(0.0, 9.5), timings=timings
    )
    # 各行の音声に合わせて表示し、最後の行は表示区間の終わりまで残す
    assert [(c.start, c.end) for c in clips] == [(1.0, 3.0), (3.5, 6.5), (7.0, 9.5)]


def test_subtitle_timings_clipped_by_window() -> None:
    script = VideoScript.model_validate({
        "video": {},
        "scenes": [{"id": "s1", "image": "a.png", "duration": 10.0, "voiceover": "一行目\n二行目"}],
    })
    renderer = Renderer(script, config=AppConfig())
    clips = renderer._create_subtitle_clip(
        script.scenes[0], text="一行目\n二行目", window=(2.0, 8.0), timings=[(1.0, 4.0), (4.5, 9.0)]
    )
    assert [(c.start, c.end) for c in clips] == [(2.0, 4.0), (4.5, 8.0)]


def _write_wav(path: Path, seconds: float) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * int(24000 * seconds))
    return path


@pytest.fixture
def fake_voice(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """1文字0.2秒の音声を返す偽のVoicebox。"""

    def synthesize(self, *, text, voice, speed=None, pitch=None):
        path = self.cache_dir / f"{abs(hash(text))}.wav"
        if not path.exists():
            _write_wav(path, 0.2 * len(text))
        return path

    monkeypatch.setattr(voicebox_module.VoiceboxClient, "synthesize", synthesize)


def test_render_extends_short_duration(tmp_path: Path, fake_voice, monkeypatch) -> None:
    Image.new("RGB", (64, 48), "navy").save(tmp_path / "bg.png")
    script_path = tmp_path / "story.yaml"
    # 10文字 + 10文字 = 2.0秒 + 行間0.5秒 + 2.0秒、前後の無音1.0秒 + 0.5秒 -> 6.0秒必要だが3秒を指定
    script_path.write_text(
        "video:\n  width: 64\n  height: 48\n  fps: 5\n"
        "scenes:\n  - id: s1\n    image: bg.png\n    duration: 3\n"
        "    voiceover: |\n      一二三四五六七八九十\n      十九八七六五四三二一\n",
        encoding="utf-8",
    )
    config = AppConfig(
        voice_margin_before=1.0, voice_margin_after=0.5, subtitle_line_interval=0.5, video_encoder="cpu"
    )
    pipeline = VideoPipeline(script_path, config=config, override_voice_cache=tmp_path / "cache")

    captured = {}
    original = Renderer.__init__

    def spy(self, *args, **kwargs):
        original(self, *args, **kwargs)
        captured["timings"] = self.line_timings

    monkeypatch.setattr(Renderer, "__init__", spy)
    pipeline.render(output_path=tmp_path / "out.mp4")

    assert pipeline.script.scenes[0].duration == pytest.approx(6.0, abs=0.01)
    timings = captured["timings"]["s1"]
    assert timings[0] == pytest.approx((1.0, 3.0), abs=0.01)
    assert timings[1] == pytest.approx((3.5, 5.5), abs=0.01)


def test_render_keeps_longer_duration(tmp_path: Path, fake_voice) -> None:
    Image.new("RGB", (64, 48), "navy").save(tmp_path / "bg.png")
    script_path = tmp_path / "story.yaml"
    script_path.write_text(
        "video:\n  width: 64\n  height: 48\n  fps: 5\n"
        "scenes:\n  - id: s1\n    image: bg.png\n    duration: 4\n    voiceover: 短い\n",
        encoding="utf-8",
    )
    pipeline = VideoPipeline(
        script_path, config=AppConfig(video_encoder="cpu"), override_voice_cache=tmp_path / "cache"
    )
    pipeline.render(output_path=tmp_path / "out.mp4")
    # ナレーション（0.4秒）より長いdurationはそのまま
    assert pipeline.script.scenes[0].duration == 4
