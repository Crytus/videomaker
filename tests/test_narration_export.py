"""ナレーション音声の書き出し（videomaker narration）のテスト。"""

import wave
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from videomaker import voicebox as voicebox_module
from videomaker.cli import _default_narration_output, _narration_format, app
from videomaker.config import AppConfig
from videomaker.errors import VideoMakerError
from videomaker.pipeline import VideoPipeline

# 偽の音声の振幅（無音と区別できる一定値）
TONE = 8000


def _write_tone(path: Path, seconds: float) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(np.full(int(24000 * seconds), TONE, dtype="<i2").tobytes())
    return path


@pytest.fixture
def fake_voice(monkeypatch: pytest.MonkeyPatch):
    """1文字0.2秒の、一定振幅の音声を返す偽のVoicebox。"""

    def synthesize(self, *, text, voice, speed=None, pitch=None):
        path = self.cache_dir / f"{abs(hash(text))}.wav"
        if not path.exists():
            _write_tone(path, 0.2 * len(text))
        return path

    monkeypatch.setattr(voicebox_module.VoiceboxClient, "synthesize", synthesize)


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    """WAVを読み、チャンネルごとの最大振幅の列とサンプリングレートを返す。"""
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        channels = w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return np.abs(data.reshape(-1, channels).astype(np.int32)).max(axis=1), rate


def _sound_spans(path: Path, threshold: int = TONE // 4) -> tuple[list[tuple[float, float]], float]:
    """音が鳴っている区間（秒）の一覧と、全体の長さを返す。"""
    amplitude, rate = _read_wav(path)
    loud = amplitude > threshold
    spans = []
    start = None
    for i, flag in enumerate(loud):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            spans.append((start / rate, i / rate))
            start = None
    if start is not None:
        spans.append((start / rate, len(loud) / rate))
    return spans, len(amplitude) / rate


def _make_script(tmp_path: Path, scenes: str, video: str = "") -> Path:
    Image.new("RGB", (64, 48), "navy").save(tmp_path / "bg.png")
    script_path = tmp_path / "story.yaml"
    script_path.write_text(
        "video:\n  width: 64\n  height: 48\n  fps: 5\n" + video + "scenes:\n" + scenes,
        encoding="utf-8",
    )
    return script_path


def _pipeline(script_path: Path, tmp_path: Path, **config) -> VideoPipeline:
    config.setdefault("voice_margin_before", 0.5)
    config.setdefault("voice_margin_after", 0.5)
    config.setdefault("subtitle_line_interval", 0.0)
    return VideoPipeline(script_path, config=AppConfig(**config), override_voice_cache=tmp_path / "cache")


# 2つ目のシーンは10秒から始まり、間に音声の無いシーンがある
SCENES = (
    "  - id: s1\n    image: bg.png\n    voiceover: あいう\n"
    "  - id: blank\n    image: bg.png\n    duration: 3\n"
    "  - id: s2\n    image: bg.png\n    start: 10\n    voiceover: えお\n"
)


def test_sync_places_narration_at_video_time(tmp_path: Path, fake_voice) -> None:
    script_path = _make_script(tmp_path, SCENES, video="  scene_interval: 0.4\n")
    out = tmp_path / "narration.wav"
    _pipeline(script_path, tmp_path).export_narration(output_path=out, mode="sync")

    spans, total = _sound_spans(out)
    # s1: 前の無音0.5秒の後に0.6秒。s2: 10秒 + 前の無音0.5秒の後に0.4秒。全体は動画と同じ 10 + 1.4秒
    assert len(spans) == 2
    assert spans[0] == pytest.approx((0.5, 1.1), abs=0.02)
    assert spans[1] == pytest.approx((10.5, 10.9), abs=0.02)
    assert total == pytest.approx(11.4, abs=0.02)


def test_sync_matches_video_with_crossfade(tmp_path: Path, fake_voice) -> None:
    """クロスフェードで重なる分だけ、後ろのシーンの音声が前に詰まる（動画と同じ）。"""
    script_path = _make_script(
        tmp_path,
        "  - id: s1\n    image: bg.png\n    voiceover: あいう\n"
        "  - id: s2\n    image: bg.png\n    voiceover: えお\n",
        video="  transition: crossfade\n  transition_duration: 0.8\n",
    )
    out = tmp_path / "narration.wav"
    _pipeline(script_path, tmp_path).export_narration(output_path=out, mode="sync")

    spans, total = _sound_spans(out)
    # s1は1.6秒、s2は1.4秒。クロスフェードは短い方のシーンの半分（0.7秒）に縮められるので、
    # s2は 1.6 - 0.7 = 0.9秒から始まり、音声は前の無音0.5秒の後の1.4秒から鳴る
    assert spans[0] == pytest.approx((0.5, 1.1), abs=0.02)
    assert spans[1] == pytest.approx((1.4, 1.8), abs=0.02)
    assert total == pytest.approx(0.9 + 1.4, abs=0.02)


def test_concat_removes_gaps(tmp_path: Path, fake_voice) -> None:
    script_path = _make_script(tmp_path, SCENES, video="  scene_interval: 0.4\n")
    out = tmp_path / "narration.wav"
    _pipeline(script_path, tmp_path).export_narration(output_path=out, mode="concat")

    spans, total = _sound_spans(out)
    # s1(0.5 + 0.6 + 0.5) + 切り替えの間0.4 + s2(0.5 + 0.4 + 0.5)。音声の無いシーンは含めない
    assert spans[0] == pytest.approx((0.5, 1.1), abs=0.02)
    assert spans[1] == pytest.approx((2.5, 2.9), abs=0.02)
    assert total == pytest.approx(3.4, abs=0.02)


def test_concat_uses_scene_interval(tmp_path: Path, fake_voice) -> None:
    script_path = _make_script(
        tmp_path,
        "  - id: s1\n    image: bg.png\n    voiceover: あ\n    interval: 1.0\n"
        "  - id: s2\n    image: bg.png\n    voiceover: い\n",
        video="  scene_interval: 0.4\n",
    )
    out = tmp_path / "narration.wav"
    _pipeline(script_path, tmp_path, voice_margin_before=0.0, voice_margin_after=0.0).export_narration(
        output_path=out, mode="concat"
    )
    spans, total = _sound_spans(out)
    # シーンの interval（1.0秒）を video.scene_interval より優先する
    assert spans[1][0] == pytest.approx(1.2, abs=0.02)
    assert total == pytest.approx(1.4, abs=0.02)


def test_volume_is_applied(tmp_path: Path, fake_voice) -> None:
    script_path = _make_script(
        tmp_path,
        "  - id: s1\n    image: bg.png\n    voiceover: あいう\n"
        "  - id: s2\n    image: bg.png\n    voiceover: えお\n    voice_override:\n      volume: 0.5\n",
    )
    out = tmp_path / "narration.wav"
    _pipeline(script_path, tmp_path).export_narration(output_path=out, mode="concat")
    amplitude, rate = _read_wav(out)
    # s1（0.5〜1.1秒）は元の音量、s2（2.1〜2.5秒）は半分の音量
    normal = amplitude[int(0.6 * rate):int(1.0 * rate)].max()
    half = amplitude[int(2.2 * rate):int(2.4 * rate)].max()
    assert half / normal == pytest.approx(0.5, rel=0.05)


def test_selected_scene_only(tmp_path: Path, fake_voice) -> None:
    script_path = _make_script(tmp_path, SCENES)
    out = tmp_path / "narration.wav"
    _pipeline(script_path, tmp_path).export_narration(output_path=out, scene_ids=["s2"])
    spans, total = _sound_spans(out)
    assert spans == [pytest.approx((0.5, 0.9), abs=0.02)]
    assert total == pytest.approx(1.4, abs=0.02)


@pytest.mark.parametrize("audio_format, suffix", [("mp3", ".mp3"), ("aac", ".m4a")])
def test_compressed_formats(tmp_path: Path, fake_voice, audio_format: str, suffix: str) -> None:
    from moviepy import AudioFileClip

    script_path = _make_script(tmp_path, "  - id: s1\n    image: bg.png\n    voiceover: あいうえお\n")
    out = tmp_path / f"narration{suffix}"
    _pipeline(script_path, tmp_path).export_narration(output_path=out, audio_format=audio_format)
    clip = AudioFileClip(str(out))
    try:
        # 0.5 + 1.0 + 0.5秒（圧縮形式はフレーム単位の端数が付くことがある）
        assert clip.duration == pytest.approx(2.0, abs=0.1)
    finally:
        clip.close()


def test_no_narration_is_error(tmp_path: Path, fake_voice) -> None:
    script_path = _make_script(tmp_path, "  - id: s1\n    image: bg.png\n    duration: 2\n")
    with pytest.raises(VideoMakerError, match="出力するナレーションがありません"):
        _pipeline(script_path, tmp_path).export_narration(output_path=tmp_path / "n.wav")


def test_no_voice_script_is_error(tmp_path: Path, fake_voice) -> None:
    script_path = _make_script(tmp_path, "  - id: s1\n    image: bg.png\n    voiceover: あ\n")
    script_path.write_text(script_path.read_text(encoding="utf-8") + "options:\n  no_voice: true\n", encoding="utf-8")
    with pytest.raises(VideoMakerError, match="音声なしモード"):
        _pipeline(script_path, tmp_path).export_narration(output_path=tmp_path / "n.wav")


def test_narration_format_resolution() -> None:
    import typer

    assert _narration_format(None, None) == "wav"
    assert _narration_format(Path("a.mp3"), None) == "mp3"
    assert _narration_format(Path("a.M4A"), None) == "aac"
    assert _narration_format(Path("a.aac"), None) == "aac"
    # --format が拡張子より優先
    assert _narration_format(Path("a.wav"), "MP3") == "mp3"
    with pytest.raises(typer.BadParameter):
        _narration_format(Path("a.ogg"), None)
    with pytest.raises(typer.BadParameter):
        _narration_format(None, "flac")


def test_default_output_name(tmp_path: Path) -> None:
    script_path = _make_script(tmp_path, "  - id: s1\n    image: bg.png\n    duration: 1\n")
    pipeline = _pipeline(script_path, tmp_path)
    assert _default_narration_output(pipeline, script_path, mode="sync", audio_format="wav") == Path(
        "dist/story_narration.wav"
    )
    assert _default_narration_output(pipeline, script_path, mode="concat", audio_format="aac") == Path(
        "dist/story_narration_concat.m4a"
    )


def test_cli_narration(tmp_path: Path, fake_voice) -> None:
    script_path = _make_script(tmp_path, "  - id: s1\n    image: bg.png\n    voiceover: あいう\n")
    out = tmp_path / "out" / "n.mp3"
    result = CliRunner().invoke(
        app,
        ["narration", str(script_path), "--out", str(out), "--mode", "concat",
         "--voice-cache", str(tmp_path / "cache")],
    )
    assert result.exit_code == 0, result.output
    assert out.exists() and out.stat().st_size > 0


def test_cli_rejects_unknown_mode(tmp_path: Path) -> None:
    script_path = _make_script(tmp_path, "  - id: s1\n    image: bg.png\n    voiceover: あ\n")
    result = CliRunner().invoke(app, ["narration", str(script_path), "--mode", "packed"])
    assert result.exit_code != 0
