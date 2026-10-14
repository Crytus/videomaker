"""ミュージックビデオ向け機能（開始時刻の指定・ナレーションなしシーン・BGM設定）のテスト。"""

import wave
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from videomaker.config import AppConfig
from videomaker.errors import ScriptError
from videomaker.models import VideoScript, parse_time
from videomaker.pipeline import VideoPipeline
from videomaker.renderer import Renderer
from videomaker.script_parser import parse_script
from videomaker.timeline import resolve_durations
from videomaker.transitions import Transition, fit_to_starts


def _script(scenes: list[dict], **video) -> VideoScript:
    return VideoScript.model_validate({"video": video, "scenes": scenes})


def _scene(scene_id: str, **extra) -> dict:
    return {"id": scene_id, "image": "a.png", **extra}


def _write_tone(path: Path, seconds: float, rate: int = 8000) -> Path:
    """振幅が一定のWAVを作る（音量の確認をしやすいよう直流にする）。"""
    samples = np.full(int(rate * seconds), 8000, dtype="<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return path


# ---- 時刻の指定 ----

@pytest.mark.parametrize(
    ("value", "expected"),
    [(12, 12.0), (1.5, 1.5), ("83.5", 83.5), ("1:23.5", 83.5), ("01:02:03", 3723.0), ("0:00", 0.0)],
)
def test_parse_time(value, expected) -> None:
    assert parse_time(value) == pytest.approx(expected)


@pytest.mark.parametrize("value", ["abc", "1:60", "1::2", "1:2:3:4", "1.5:10", -1, True])
def test_parse_time_invalid(value) -> None:
    with pytest.raises(ValueError):
        parse_time(value)


def test_voiceover_is_optional() -> None:
    script = _script([_scene("a", duration=3), _scene("b", duration=2, voiceover=None)])
    assert [s.voiceover for s in script.scenes] == ["", ""]


def test_start_accepts_time_string() -> None:
    script = _script([_scene("a", start=0), _scene("b", start="1:05.5")], bgm_start="0:10")
    assert script.scenes[1].start == pytest.approx(65.5)
    assert script.video.bgm_start == pytest.approx(10.0)


def test_first_scene_start_must_be_zero() -> None:
    with pytest.raises(ValueError, match="最初のシーン"):
        _script([_scene("a", start=3), _scene("b", start=5)])


def test_start_must_increase() -> None:
    with pytest.raises(ValueError, match="start"):
        _script([_scene("a"), _scene("b", start=10), _scene("c", start=10)])


# ---- シーンの長さの決定 ----

def test_resolve_durations_by_start() -> None:
    script = _script([_scene("a"), _scene("b", start=4.5), _scene("c", start="0:12", duration=3), _scene("d", duration=3)])
    starts = resolve_durations(script.scenes)
    assert starts == pytest.approx([0.0, 4.5, 12.0, 15.0])
    assert [s.duration for s in script.scenes] == pytest.approx([4.5, 7.5, 3.0, 3.0])


def test_resolve_durations_start_overrides_duration_and_narration() -> None:
    # startが最優先。durationやナレーションが長くても次のstartで区切る
    script = _script([_scene("a", duration=10, voiceover="x"), _scene("b", start=4, duration=2)])
    resolve_durations(script.scenes, narration={"a": 6.0})
    assert [s.duration for s in script.scenes] == pytest.approx([4.0, 2.0])


def test_resolve_durations_unpinned_scene_absorbs_gap() -> None:
    # startの無いシーンが挟まる場合は、次のstartの直前のシーンで長さを合わせる
    script = _script([_scene("a", duration=3), _scene("b", duration=2), _scene("c", start=10, duration=1)])
    starts = resolve_durations(script.scenes)
    assert starts == pytest.approx([0.0, 3.0, 10.0])
    assert [s.duration for s in script.scenes] == pytest.approx([3.0, 7.0, 1.0])


def test_resolve_durations_extends_short_duration_by_narration() -> None:
    script = _script([_scene("a", duration=2, voiceover="x"), _scene("b", voiceover="y")])
    resolve_durations(script.scenes, narration={"a": 3.5, "b": 1.5})
    assert [s.duration for s in script.scenes] == pytest.approx([3.5, 1.5])


def test_resolve_durations_last_scene_until_bgm_end() -> None:
    script = _script([_scene("a"), _scene("b", start=5)])
    resolve_durations(script.scenes, bgm_remaining=12.0)
    assert [s.duration for s in script.scenes] == pytest.approx([5.0, 7.0])


def test_resolve_durations_uses_media_length() -> None:
    script = _script([_scene("a", duration=1), {"id": "v", "video": "v.mp4"}])
    resolve_durations(script.scenes, media={"v": 4.2})
    assert script.scenes[1].duration == pytest.approx(4.2)


def test_resolve_durations_unknown_length() -> None:
    script = _script([_scene("a"), _scene("b", duration=2)])
    with pytest.raises(ScriptError, match="長さが決まりません"):
        resolve_durations(script.scenes)


def test_resolve_durations_last_scene_without_bgm() -> None:
    script = _script([_scene("a", duration=2), _scene("b")])
    with pytest.raises(ScriptError, match="シーン b の長さが決まりません"):
        resolve_durations(script.scenes)


def test_resolve_durations_start_before_previous_end() -> None:
    script = _script([_scene("a", duration=5), _scene("b", duration=5), _scene("c", start=4, duration=1)])
    with pytest.raises(ScriptError, match="以前になっています"):
        resolve_durations(script.scenes)


def test_resolve_durations_bgm_already_ended() -> None:
    script = _script([_scene("a"), _scene("b", start=10)])
    with pytest.raises(ScriptError, match="BGMの終わりより後"):
        resolve_durations(script.scenes, bgm_remaining=8.0)


# ---- クロスフェードと開始時刻 ----

def test_fit_to_starts_with_crossfade() -> None:
    plans = [Transition(), Transition("crossfade", 1.0), Transition("crossfade", 0.5), Transition()]
    durations = fit_to_starts([4.0, 6.0, 3.0, 2.0], plans, [None, 4.0, None, 12.0])
    # bは4秒ちょうどにフェードインし始めるよう、aを重なりの分だけ延ばす
    assert durations[0] == pytest.approx(5.0)
    # cは b の終わり（4 + 6 - 0.5 = 9.5秒）から始まるので、dが12秒に始まるよう cは2.5秒
    assert durations[2] == pytest.approx(2.5)
    assert durations[1] == pytest.approx(6.0)


def test_fixed_starts_with_scene_selection() -> None:
    script = _script(
        [_scene("a", duration=1), _scene("b", start=2), _scene("c", start=5),
         _scene("d", start=7), _scene("e", start=9, duration=1)]
    )
    renderer = Renderer(script, start_offset=2.0)
    scenes = [script.scenes[i] for i in (1, 2, 4)]  # b, c, e（dが抜けている）
    # 連続している c までは開始時刻を合わせ、抜けた箇所より後ろ（e）は合わせない
    assert renderer._fixed_starts(scenes) == [None, 3.0, None]


# ---- 書き出し ----

def _write_mv_script(tmp_path: Path, extra_video: str = "", scenes: str | None = None) -> Path:
    Image.new("RGB", (64, 48), "navy").save(tmp_path / "a.png")
    Image.new("RGB", (64, 48), "white").save(tmp_path / "b.png")
    _write_tone(tmp_path / "song.wav", 6.0)
    if scenes is None:
        scenes = (
            "  - id: intro\n    image: a.png\n    subtitle: イントロ\n"
            "  - id: verse\n    image: b.png\n    start: 2\n    subtitle: 一番の歌詞\n"
            "  - id: chorus\n    image: a.png\n    start: \"0:04\"\n    subtitle: サビの歌詞\n"
        )
    script_path = tmp_path / "mv.yaml"
    script_path.write_text(
        "video:\n  width: 64\n  height: 48\n  fps: 10\n  bgm: song.wav\n"
        "  transition: crossfade\n  transition_duration: 0.5\n"
        f"{extra_video}"
        f"scenes:\n{scenes}",
        encoding="utf-8",
    )
    return script_path


@pytest.fixture
def capture_renderer(monkeypatch: pytest.MonkeyPatch):
    """Rendererのタイムラインと開始オフセットを記録する。"""
    captured: dict = {}
    original = Renderer.render

    def spy(self, **kwargs):
        result = original(self, **kwargs)
        captured["timeline"] = [(scene.id, start, end) for scene, start, end, _ in self.timeline]
        captured["offset"] = self.start_offset
        return result

    monkeypatch.setattr(Renderer, "render", spy)
    return captured


def test_render_music_video_without_voiceover(tmp_path: Path, capture_renderer, monkeypatch) -> None:
    from moviepy import VideoFileClip

    # ナレーションが無いのでVoiceboxには接続しない
    monkeypatch.setattr(VideoPipeline, "_voice_client", lambda self: pytest.fail("Voiceboxに接続しました"))
    script_path = _write_mv_script(tmp_path, "  bgm_volume: 1.0\n  bgm_loop: false\n")
    out = tmp_path / "out.mp4"
    VideoPipeline(script_path, config=AppConfig(video_encoder="cpu")).render(output_path=out)

    timeline = capture_renderer["timeline"]
    # クロスフェードがあっても、startを指定したシーンは指定時刻ちょうどに始まる
    assert [start for _, start, _ in timeline] == pytest.approx([0.0, 2.0, 4.0])
    # 最後のシーンはBGMの終わり（6秒）まで
    assert timeline[-1][2] == pytest.approx(6.0)

    clip = VideoFileClip(str(out))
    try:
        assert clip.duration == pytest.approx(6.0, abs=0.15)
        assert clip.audio is not None
    finally:
        clip.close()


def test_render_selected_scene_starts_bgm_at_scene_start(tmp_path: Path, capture_renderer) -> None:
    script_path = _write_mv_script(tmp_path)
    VideoPipeline(script_path, config=AppConfig(video_encoder="cpu")).render(
        output_path=tmp_path / "out.mp4", scene_ids=["verse"]
    )
    # --scene で途中のシーンだけ書き出すと、BGMはそのシーンの開始時刻から再生する
    assert capture_renderer["offset"] == pytest.approx(2.0)
    assert capture_renderer["timeline"] == [("verse", 0.0, pytest.approx(2.0))]


def test_apply_bgm_volume_start_and_fade(tmp_path: Path) -> None:
    from moviepy import ColorClip

    _write_tone(tmp_path / "song.wav", 4.0)
    script = parse_script(_write_mv_script(tmp_path, "  bgm_volume: 0.5\n  bgm_start: 1\n  bgm_fade_out: 1\n"))
    renderer = Renderer(script, start_offset=0.5)
    clip = renderer._apply_bgm(ColorClip((16, 16), color=(0, 0, 0), duration=2.0))
    # BGMは bgm_start + start_offset = 1.5秒の位置から2秒間
    assert clip.audio.duration == pytest.approx(2.0)
    # 元の音の振幅（モノラルはステレオとして読まれ、少し小さくなるので実際に読んだ値を使う）
    from moviepy import AudioFileClip

    source = AudioFileClip(str(tmp_path / "song.wav"))
    full = np.abs(source.to_soundarray(tt=np.linspace(0.1, 0.5, 50))).max()
    source.close()
    early = np.abs(clip.audio.to_soundarray(tt=np.linspace(0.1, 0.5, 50))).max()
    late = np.abs(clip.audio.to_soundarray(tt=np.linspace(1.95, 1.99, 20))).max()
    assert early == pytest.approx(full * 0.5, rel=0.05)  # 音量50%
    assert late < full * 0.5 * 0.1  # 最後はフェードアウトでほぼ無音


def test_apply_bgm_without_loop_stops_at_end(tmp_path: Path) -> None:
    from moviepy import ColorClip

    script = parse_script(_write_mv_script(tmp_path, "  bgm_loop: false\n"))
    clip = Renderer(script)._apply_bgm(ColorClip((16, 16), color=(0, 0, 0), duration=8.0))
    # ループしない場合、BGM（6秒）より後は無音
    assert clip.audio.duration == pytest.approx(6.0)


def test_render_closes_opened_media(tmp_path: Path, monkeypatch) -> None:
    # 書き出し後にBGMなどの読み込みを閉じておかないと、Python終了時に
    # 「ハンドルが無効です」(WinError 6) が表示されることがある
    opened: list = []
    original = Renderer._open_media

    def spy(self, *args):
        clip = original(self, *args)
        opened.append(clip)
        return clip

    monkeypatch.setattr(Renderer, "_open_media", spy)
    script_path = _write_mv_script(tmp_path)
    VideoPipeline(script_path, config=AppConfig(video_encoder="cpu")).render(output_path=tmp_path / "out.mp4")

    assert opened  # BGMを開いている
    assert all(clip.reader is None for clip in opened)


def test_render_closes_opened_media_on_failure(tmp_path: Path, monkeypatch) -> None:
    from videomaker.errors import RenderError

    opened: list = []
    original = Renderer._open_media

    def spy(self, *args):
        clip = original(self, *args)
        opened.append(clip)
        return clip

    def fail(*args, **kwargs):
        raise RuntimeError("書き出し失敗")

    monkeypatch.setattr(Renderer, "_open_media", spy)
    monkeypatch.setattr("moviepy.VideoClip.write_videofile", fail)
    script_path = _write_mv_script(tmp_path)
    with pytest.raises(RenderError):
        VideoPipeline(script_path, config=AppConfig(video_encoder="cpu")).render(output_path=tmp_path / "out.mp4")

    # 書き出しに失敗しても閉じる
    assert opened
    assert all(clip.reader is None for clip in opened)
