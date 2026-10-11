"""音声なしモード（アフレコ用）のテスト。"""

from pathlib import Path

import pytest
import requests
from PIL import Image
from typer.testing import CliRunner

from videomaker import voicebox as voicebox_module
from videomaker.cli import app
from videomaker.config import AppConfig
from videomaker.pipeline import VideoPipeline, _format_time

runner = CliRunner()


def _make_script(tmp_path: Path, *, options: str = "", duration: str = "") -> Path:
    Image.new("RGB", (64, 48), "navy").save(tmp_path / "bg.png")
    script = tmp_path / "story.yaml"
    script.write_text(
        "video:\n  width: 160\n  height: 120\n  fps: 5\n"
        "scenes:\n"
        "  - id: s1\n    image: bg.png\n"
        f"{duration}"
        "    voiceover: |\n      こんにちは世界\n      二行目です\n"
        "  - id: s2\n    image: bg.png\n    voiceover: 短い\n"
        f"{options}",
        encoding="utf-8",
    )
    return script


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Voiceboxに接続しようとしたら失敗させる。"""

    def fail(*args, **kwargs):
        raise AssertionError("音声なしモードでVoiceboxに接続しました")

    monkeypatch.setattr(voicebox_module.requests, "post", fail)
    monkeypatch.setattr(voicebox_module.requests, "get", fail)


def test_estimate_duration(tmp_path: Path) -> None:
    config = AppConfig(
        no_voice_chars_per_second=5.0,
        no_voice_min_duration=1.0,
        subtitle_line_interval=0.5,
        voice_margin_before=1.0,
        voice_margin_after=0.5,
    )
    pipeline = VideoPipeline(_make_script(tmp_path), config=config, no_voice=True)
    s1, s2 = pipeline.script.scenes
    # 12文字 / 5 = 2.4秒 + 行間0.5秒 + 前後1.5秒
    assert pipeline._estimate_duration(s1) == pytest.approx(4.4)
    # 2文字 / 5 = 0.4秒 は最小値1.0秒に切り上げ + 前後1.5秒
    assert pipeline._estimate_duration(s2) == pytest.approx(2.5)


def test_no_voice_from_script_option(tmp_path: Path) -> None:
    script = _make_script(tmp_path, options="options:\n  no_voice: true\n")
    assert VideoPipeline(script, config=AppConfig()).no_voice
    assert not VideoPipeline(_make_script(tmp_path), config=AppConfig()).no_voice


def test_validate_skips_voicebox(tmp_path: Path, no_network: None) -> None:
    pipeline = VideoPipeline(_make_script(tmp_path), config=AppConfig(), no_voice=True)
    pipeline.validate()


def test_format_time() -> None:
    assert _format_time(75.5) == "1:15.50"
    assert _format_time(3.0) == "0:03.00"


def test_cli_render_no_voice(tmp_path: Path, no_network: None) -> None:
    script = _make_script(tmp_path, duration="    duration: 1.5\n")
    config = tmp_path / "config.yaml"
    config.write_text("video_encoder: cpu\n", encoding="utf-8")
    out = tmp_path / "out.mp4"
    result = runner.invoke(
        app,
        ["render", str(script), "--no-voice", "--config", str(config), "--out", str(out),
         "--voice-cache", str(tmp_path / "cache")],
    )
    assert result.exit_code == 0, result.output
    assert out.exists() and out.stat().st_size > 0
    assert "アフレコ用タイムテーブル" in result.output
    # 音声キャッシュは作られない
    assert not list((tmp_path / "cache").glob("*.wav"))

    from moviepy import VideoFileClip

    clip = VideoFileClip(str(out))
    try:
        # s1は指定の1.5秒、s2は「短い」の見積もり（最小2.0秒）
        assert clip.duration == pytest.approx(3.5, abs=0.3)
        assert clip.audio is None
    finally:
        clip.close()


def test_default_output_name_has_suffix(tmp_path: Path) -> None:
    from videomaker.cli import _default_output

    script = _make_script(tmp_path)
    pipeline = VideoPipeline(script, config=AppConfig(), no_voice=True)
    assert _default_output(pipeline, script, preview=True).name == "story_novoice_preview.mp4"
