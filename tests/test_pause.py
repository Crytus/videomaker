"""ナレーション中の無音（{無音 0.5}）とシーン切り替えの間（scene_interval / interval）のテスト。"""

from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from videomaker.config import AppConfig
from videomaker.models import VideoScript
from videomaker.narration import split_narration, strip_pauses
from videomaker.pipeline import VideoPipeline, _segment_timings
from videomaker.renderer import Renderer
from videomaker.timeline import resolve_durations

# tests/test_timing.py の偽のVoicebox（1文字0.2秒）を使う
from test_timing import fake_voice  # noqa: F401


def test_split_narration_inline_pause() -> None:
    lines = split_narration("春の山道には{無音 0.5}小鳥の声が響きます。", 30)
    assert len(lines) == 1
    assert lines[0].text == "春の山道には小鳥の声が響きます。"
    assert lines[0].segments == ["春の山道には", 0.5, "小鳥の声が響きます。"]


def test_split_narration_pause_line_and_variants() -> None:
    text = "{無音 1}\n一行目です。\n｛無音　0.3秒｝\n二行目です。{無音 2}\n"
    lines = split_narration(text, 30)
    assert [line.text for line in lines] == ["一行目です。", "二行目です。"]
    # 無音だけの行は前の行の後ろへ、最初なら次の行の前へ
    assert lines[0].segments == [1.0, "一行目です。", 0.3]
    assert lines[1].segments == ["二行目です。", 2.0]


def test_split_narration_folded_text() -> None:
    # YAMLの「>」で折り返した場合（タグの前後が半角空白になる）
    lines = split_narration("山道を歩きます。 {無音 0.5} 小川があります。", 30)
    assert lines[0].text == "山道を歩きます。小川があります。"
    assert lines[0].segments == ["山道を歩きます。", 0.5, "小川があります。"]


def test_split_narration_same_as_text_lines_without_pause() -> None:
    from videomaker.textsplit import split_text_lines

    text = "山道からはずっと八ヶ岳が望めます。春先の八ヶ岳はまだ山頂付近に雪が残っています。"
    assert [line.text for line in split_narration(text, 20)] == split_text_lines(text, 20)


def test_long_line_splits_at_pause() -> None:
    lines = split_narration("ああああああああああ{無音 0.5}いいいいいいいいいい", 12)
    assert [line.text for line in lines] == ["ああああああああああ", "いいいいいいいいいい"]
    assert lines[0].segments == ["ああああああああああ", 0.5]


def test_strip_pauses() -> None:
    assert strip_pauses("あ{無音 0.5}い") == "あい"


def test_split_narration_mute_tag() -> None:
    # 「無音」の代わりに「mute」も使える（大文字小文字・末尾の「s」「秒」も可）
    text = "{mute 1}\n一行目です。\n｛MUTE　0.3s｝\n二行目{Mute 0.5秒}です。"
    lines = split_narration(text, 30)
    assert [line.text for line in lines] == ["一行目です。", "二行目です。"]
    assert lines[0].segments == [1.0, "一行目です。", 0.3]
    assert lines[1].segments == ["二行目", 0.5, "です。"]
    assert strip_pauses("Hello {mute 0.5} world") == "Helloworld"


@pytest.mark.parametrize(
    "voiceover", ["あ{無音}い", "あ{無音 abc}い", "{無音 1}", "あ{mute}い", "あ{mute 1x}い", "{mute 1}"]
)
def test_invalid_pause_tag(voiceover: str) -> None:
    with pytest.raises(ValidationError):
        VideoScript.model_validate({
            "video": {}, "scenes": [{"id": "s", "image": "a.png", "voiceover": voiceover}],
        })


def test_segment_timings() -> None:
    lines = [
        [("silence", 1.0), ("speech", 2.0), ("silence", 0.5), ("speech", 1.0), ("silence", 0.3)],
        [("speech", 2.0)],
    ]
    # 前の無音0.5秒、行間0.2秒
    assert _segment_timings(lines, 0.5, 0.2) == [(1.5, 5.0), (5.5, 7.5)]


def test_subtitle_hides_pause_tag() -> None:
    script = VideoScript.model_validate({
        "video": {},
        "scenes": [{"id": "s1", "image": "a.png", "duration": 5.0, "voiceover": "こんにちは{無音 0.5}世界"}],
    })
    renderer = Renderer(script, config=AppConfig())
    clips = renderer._create_subtitle_clip(script.scenes[0], text=script.scenes[0].voiceover)
    clips = clips if isinstance(clips, list) else [clips]
    assert [c.text for c in clips if hasattr(c, "text")] == ["こんにちは世界"]


def _scenes(*specs: dict, video: dict | None = None) -> VideoScript:
    return VideoScript.model_validate({"video": video or {}, "scenes": [
        {"image": "a.png", **spec} for spec in specs
    ]})


def test_scene_interval_default_and_override() -> None:
    script = _scenes({"id": "a"}, {"id": "b", "interval": 0.2}, {"id": "c"}, video={"scene_interval": 1.0})
    starts = resolve_durations(
        script.scenes, narration={"a": 3.0, "b": 2.0, "c": 4.0}, default_interval=1.0
    )
    # 最後のシーンは切り替えが無いので間を加えない
    assert [s.duration for s in script.scenes] == pytest.approx([4.0, 2.2, 4.0])
    assert starts == pytest.approx([0.0, 4.0, 6.2])


def test_scene_interval_not_added_to_explicit_duration() -> None:
    script = _scenes({"id": "a", "duration": 5.0}, {"id": "b", "duration": 2.0})
    resolve_durations(script.scenes, narration={"a": 3.0}, default_interval=1.0)
    assert [s.duration for s in script.scenes] == [5.0, 2.0]


def test_scene_interval_validation() -> None:
    with pytest.raises(ValidationError):
        _scenes({"id": "a", "interval": -1})


def test_estimate_duration_with_pause(tmp_path: Path) -> None:
    Image.new("RGB", (64, 48), "navy").save(tmp_path / "bg.png")
    script_path = tmp_path / "story.yaml"
    script_path.write_text(
        "video: {}\nscenes:\n  - id: s1\n    image: bg.png\n    voiceover: あいうえお{無音 1.5}かきくけこ\n",
        encoding="utf-8",
    )
    config = AppConfig(no_voice_chars_per_second=5.0, no_voice_min_duration=0.1)
    pipeline = VideoPipeline(script_path, config=config, no_voice=True)
    # 10文字 / 5 = 2秒 + 無音1.5秒
    assert pipeline._estimate_duration(pipeline.script.scenes[0]) == pytest.approx(3.5)


def test_render_with_pause_and_scene_interval(tmp_path: Path, fake_voice, monkeypatch) -> None:  # noqa: F811
    Image.new("RGB", (64, 48), "navy").save(tmp_path / "bg.png")
    script_path = tmp_path / "story.yaml"
    # s1: 5文字(1.0秒) + 無音0.5秒 + 5文字(1.0秒) = 2.5秒、前の無音0.2秒 + 切り替えの間0.8秒 -> 3.5秒
    # s2: 2文字(0.4秒) + 前の無音0.2秒 = 0.6秒（最後のシーンなので間なし）
    script_path.write_text(
        "video:\n  width: 64\n  height: 48\n  fps: 5\n  scene_interval: 0.8\n"
        "scenes:\n"
        "  - id: s1\n    image: bg.png\n    voiceover: あいうえお{無音 0.5}かきくけこ\n"
        "  - id: s2\n    image: bg.png\n    voiceover: 短い\n",
        encoding="utf-8",
    )
    config = AppConfig(voice_margin_before=0.2, video_encoder="cpu")
    pipeline = VideoPipeline(script_path, config=config, override_voice_cache=tmp_path / "cache")

    captured = {}
    original = Renderer.__init__

    def spy(self, *args, **kwargs):
        original(self, *args, **kwargs)
        captured["timings"] = self.line_timings

    monkeypatch.setattr(Renderer, "__init__", spy)
    pipeline.render(output_path=tmp_path / "out.mp4")

    s1, s2 = pipeline.script.scenes
    assert s1.duration == pytest.approx(3.5, abs=0.01)
    assert s2.duration == pytest.approx(0.6, abs=0.01)
    # 字幕は1行で、無音の間も表示したまま
    assert captured["timings"]["s1"] == [pytest.approx((0.2, 2.7), abs=0.01)]
    assert (tmp_path / "out.mp4").exists()
