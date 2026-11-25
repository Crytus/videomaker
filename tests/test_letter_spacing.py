"""字幕・テロップの字間（letter_spacing）のテスト。"""

from pathlib import Path

import numpy as np
import pytest

from videomaker.config import AppConfig
from videomaker.models import VideoScript
from videomaker.renderer import Renderer, _text_bbox, make_text_clip

FONT = Path("assets/fonts/msgothic.ttc")
needs_font = pytest.mark.skipif(not FONT.exists(), reason="テスト用フォントがありません")


def _script(video: dict, scene: dict) -> VideoScript:
    return VideoScript.model_validate({
        "video": {"width": 640, "height": 360, **video},
        "scenes": [{"id": "s1", "image": "a.png", "duration": 2.0, "voiceover": "字幕です", **scene}],
    })


def _width(clip) -> int:
    x0, _, x1, _ = _text_bbox(clip)
    return x1 - x0


@needs_font
def test_letter_spacing_widens_text() -> None:
    text = "字間の調整"
    base = make_text_clip(text, str(FONT), 40, "#FFFFFF", "#000000", 2, duration=1)
    wide = make_text_clip(text, str(FONT), 40, "#FFFFFF", "#000000", 2, duration=1, letter_spacing=10)
    narrow = make_text_clip(text, str(FONT), 40, "#FFFFFF", "#000000", 2, duration=1, letter_spacing=-4)
    # 字間 × (文字数 - 1) だけ幅が変わる（描画の誤差は数px以内）
    assert abs(_width(wide) - _width(base) - 10 * 4) <= 2
    assert abs(_width(base) - _width(narrow) - 4 * 4) <= 2
    # 高さはTextClipと同じ
    assert wide.size[1] == base.size[1]
    assert wide.duration == 1


@needs_font
def test_letter_spacing_keeps_center_in_fixed_width() -> None:
    clip = make_text_clip("中央寄せ", str(FONT), 40, "#FFFFFF", None, 0, size=(600, None), letter_spacing=12)
    assert clip.size[0] == 600
    x0, _, x1, _ = _text_bbox(clip)
    assert abs((x0 + x1) / 2 - 300) <= 3


def test_letter_spacing_resolution() -> None:
    # video.subtitle.letter_spacing は字幕・テロップ共通、style の指定が優先
    script = _script(
        {"subtitle": {"letter_spacing": 6, "style": {"letter_spacing": 8}}, "teletext": {"style": {}}},
        {"subtitle": {"text": "字幕", "style": {"letter_spacing": 3}}, "teletext": {"text": "テロップ"}},
    )
    scene = script.scenes[0]
    assert scene.subtitle_config.style.letter_spacing == 3
    assert scene.subtitle_config.letter_spacing == 6
    assert script.video.subtitle.style.letter_spacing == 8
    assert scene.teletext.style.letter_spacing is None


@needs_font
def test_renderer_applies_letter_spacing() -> None:
    def widths(spacing: float) -> tuple[int, int]:
        script = _script(
            {"subtitle": {"font": str(FONT), "letter_spacing": spacing}},
            {"teletext": {"text": "テロップ", "position": "center"}},
        )
        renderer = Renderer(script, config=AppConfig())
        subtitle = renderer._create_subtitle_clip(script.scenes[0], text="字幕です")
        teletext = renderer._create_teletext_clip(script.scenes[0])
        return _width(subtitle), _width(teletext)

    (sub0, tel0), (sub1, tel1) = widths(0), widths(10)
    assert abs(sub1 - sub0 - 30) <= 2
    assert abs(tel1 - tel0 - 30) <= 2
