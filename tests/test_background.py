"""字幕・テロップの背景色のテスト。"""

from pathlib import Path

import numpy as np
import pytest

from videomaker.config import AppConfig, load_config
from videomaker.errors import ConfigError, ScriptError
from videomaker.models import VideoScript, parse_color
from videomaker.renderer import Renderer
from videomaker.script_parser import parse_script


def test_parse_color() -> None:
    assert parse_color("#000000") == (0, 0, 0, 255)
    assert parse_color("#00000080") == (0, 0, 0, 128)
    assert parse_color("#fff") == (255, 255, 255, 255)
    assert parse_color("red") == (255, 0, 0, 255)
    # 不透明度はアルファ値に掛け合わせる
    assert parse_color("#1E3A5F", 0.5) == (30, 58, 95, 128)
    assert parse_color("#00000080", 0.5) == (0, 0, 0, 64)


def test_invalid_color_in_script(tmp_path: Path) -> None:
    path = tmp_path / "story.yaml"
    path.write_text(
        "video: {}\nscenes:\n  - id: s1\n    image: a.png\n    voiceover: x\n"
        "    teletext:\n      text: t\n      style:\n        background: '#12'\n",
        encoding="utf-8",
    )
    with pytest.raises(ScriptError, match="色の指定が不正です"):
        parse_script(path)


def test_invalid_color_in_config(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("teletext_background: notacolor\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="色の指定が不正です"):
        load_config(path)


def _script(teletext: dict, subtitle_style: dict | None = None) -> VideoScript:
    return VideoScript.model_validate({
        "video": {"width": 640, "height": 360, "subtitle": {"style": subtitle_style or {}}},
        "scenes": [{"id": "s1", "image": "a.png", "duration": 2.0, "voiceover": "字幕です",
                    "teletext": teletext}],
    })


def _box_alpha(box) -> float:
    return float(np.asarray(box.mask.get_frame(0)).max())


def test_teletext_background_box() -> None:
    script = _script({"text": "テロップ", "position": "top_left",
                      "style": {"background": "#00000080", "background_padding": 10}})
    result = Renderer(script, config=AppConfig())._create_teletext_clip(script.scenes[0])
    box, text = result
    # 背景は文字より余白分だけ大きく、文字の後ろに置かれる
    assert box.size[0] < text.size[0] + 40
    assert box.size[1] > 20
    assert _box_alpha(box) == pytest.approx(128 / 255, abs=0.01)
    assert box.duration == text.duration


def test_teletext_without_background_is_single_clip() -> None:
    script = _script({"text": "テロップ"})
    result = Renderer(script, config=AppConfig())._create_teletext_clip(script.scenes[0])
    assert not isinstance(result, list)


def test_teletext_background_from_config() -> None:
    script = _script({"text": "テロップ"})
    result = Renderer(script, config=AppConfig(teletext_background="#FF000040"))._create_teletext_clip(
        script.scenes[0]
    )
    assert isinstance(result, list)
    assert _box_alpha(result[0]) == pytest.approx(64 / 255, abs=0.01)


def test_teletext_right_position_is_on_screen() -> None:
    script = _script({"text": "右上のテロップ", "position": "top_right"})
    text = Renderer(script, config=AppConfig())._create_teletext_clip(script.scenes[0])
    x, _ = text.pos(0)
    assert 0 <= x and x + text.size[0] <= 640


def test_subtitle_background_fits_text() -> None:
    script = _script({"text": "t"}, subtitle_style={"background": "#000000", "background_padding": 8})
    renderer = Renderer(script, config=AppConfig())
    box, text = renderer._create_subtitle_clip(script.scenes[0], text="短い字幕")
    # 字幕のTextClipは画面幅近くまで広いが、背景は文字の部分だけを囲む
    assert text.size[0] == 640 - 200
    assert box.size[0] < 300
    assert box.start == text.start and box.duration == text.duration


def _teletext_lines(script) -> int:
    """テロップの表示行数（単一行ならクリップ1つ、複数行なら合成クリップの子の数）。"""
    result = Renderer(script, config=AppConfig())._create_teletext_clip(script.scenes[0])
    return len(result.clips) if hasattr(result, "clips") else 1


def test_teletext_wraps_by_video_setting() -> None:
    script = _script({"text": "飯盛山は八ヶ岳を望む山です"})
    assert _teletext_lines(script) == 1
    script.video.teletext_max_line_chars = 8
    assert _teletext_lines(script) == 2


def test_teletext_scene_setting_overrides_video() -> None:
    script = _script({"text": "飯盛山は八ヶ岳を望む山です", "max_line_chars": 0})
    script.video.teletext_max_line_chars = 8
    assert _teletext_lines(script) == 1
