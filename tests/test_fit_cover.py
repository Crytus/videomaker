"""素材と出力のアスペクト比が違うときに、変形せず中央（または focus の位置）を切り取ることのテスト。"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from videomaker.models import FocusSpec, SceneSpec
from videomaker.renderer import ImageClip, _center_crop_box, _fit_cover


@pytest.mark.parametrize(
    ("src", "dst", "expected"),
    [
        # 横長画像を縦動画に: 左右を削る
        ((1920, 1080), (1080, 1920), (656, 0, 1264, 1080)),
        # 縦長画像を横動画に: 上下を削る
        ((1080, 1920), (1920, 1080), (0, 656, 1080, 1264)),
        # 比率が同じなら切り取らない
        ((3840, 2160), (1920, 1080), (0, 0, 3840, 2160)),
        # 正方形画像を横動画に
        ((1000, 1000), (1920, 1080), (0, 219, 1000, 781)),
    ],
)
def test_center_crop_box(src, dst, expected) -> None:
    assert _center_crop_box(src, dst) == expected


def _stripe_image(path: Path, size: tuple[int, int]) -> Path:
    """左1/3が赤・中央が緑・右1/3が青の画像を作る。"""
    w, h = size
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[:, : w // 3] = (255, 0, 0)
    arr[:, w // 3 : w * 2 // 3] = (0, 255, 0)
    arr[:, w * 2 // 3 :] = (0, 0, 255)
    Image.fromarray(arr).save(path)
    return path


def test_fit_cover_landscape_image_to_portrait(tmp_path: Path) -> None:
    # 横長画像を縦長に合わせると、中央の緑だけが残る（変形していれば赤・青が入る）
    image = _stripe_image(tmp_path / "wide.png", (300, 100))
    clip = _fit_cover(ImageClip(str(image), duration=1), (90, 160))
    frame = clip.get_frame(0)
    assert frame.shape == (160, 90, 3)
    assert (frame[:, :, 1] > 200).all()
    assert (frame[:, :, 0] < 50).all() and (frame[:, :, 2] < 50).all()


def test_fit_cover_portrait_image_to_landscape(tmp_path: Path) -> None:
    # 縦長画像（上中下で色分け）を横長に合わせると、中央の帯が残る
    arr = np.zeros((300, 100, 3), dtype=np.uint8)
    arr[:100] = (255, 0, 0)
    arr[100:200] = (0, 255, 0)
    arr[200:] = (0, 0, 255)
    image = tmp_path / "tall.png"
    Image.fromarray(arr).save(image)
    clip = _fit_cover(ImageClip(str(image), duration=1), (160, 90))
    frame = clip.get_frame(0)
    assert frame.shape == (90, 160, 3)
    assert (frame[:, :, 1] > 200).all()


def test_fit_cover_same_ratio_keeps_whole_image(tmp_path: Path) -> None:
    image = _stripe_image(tmp_path / "same.png", (320, 180))
    clip = _fit_cover(ImageClip(str(image), duration=1), (160, 90))
    frame = clip.get_frame(0)
    assert frame.shape == (90, 160, 3)
    # 左端は赤、右端は青のまま残る
    assert frame[45, 2, 0] > 200 and frame[45, -3, 2] > 200


# --- focus（切り取る位置の指定） ---


@pytest.mark.parametrize(
    ("focus", "expected"),
    [
        # 左端・右端に寄せる
        ((0.0, 0.5), (0, 0, 608, 1080)),
        ((1.0, 0.5), (1312, 0, 1920, 1080)),
        # 中央は従来と同じ
        ((0.5, 0.5), (656, 0, 1264, 1080)),
        # 左から30%（576px）を中心にする: 576 - 304 = 272
        ((0.3, 0.5), (272, 0, 880, 1080)),
        # 端からはみ出す指定は端で止まる
        ((0.1, 0.5), (0, 0, 608, 1080)),
        ((0.9, 0.5), (1312, 0, 1920, 1080)),
        # 横長素材では y は使わない
        ((0.5, 0.0), (656, 0, 1264, 1080)),
    ],
)
def test_crop_box_with_focus_landscape_to_portrait(focus, expected) -> None:
    assert _center_crop_box((1920, 1080), (1080, 1920), focus) == expected


@pytest.mark.parametrize(
    ("focus", "expected"),
    [
        ((0.5, 0.0), (0, 0, 1080, 608)),
        ((0.5, 1.0), (0, 1312, 1080, 1920)),
        ((0.5, 0.25), (0, 176, 1080, 784)),
        # 縦長素材では x は使わない
        ((0.0, 0.5), (0, 656, 1080, 1264)),
    ],
)
def test_crop_box_with_focus_portrait_to_landscape(focus, expected) -> None:
    assert _center_crop_box((1080, 1920), (1920, 1080), focus) == expected


def test_crop_box_same_ratio_ignores_focus() -> None:
    assert _center_crop_box((3840, 2160), (1920, 1080), (0.0, 1.0)) == (0, 0, 3840, 2160)


@pytest.mark.parametrize(("focus", "channel"), [((0.0, 0.5), 0), ((1.0, 0.5), 2)])
def test_fit_cover_with_focus(tmp_path: Path, focus, channel) -> None:
    # 左寄せなら赤だけ、右寄せなら青だけが残る
    image = _stripe_image(tmp_path / "wide.png", (300, 100))
    clip = _fit_cover(ImageClip(str(image), duration=1), (90, 160), focus)
    frame = clip.get_frame(0)
    assert frame.shape == (160, 90, 3)
    assert (frame[:, :, channel] > 200).all()
    assert (frame[:, :, 1] < 50).all()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("left", (0.0, 0.5)),
        ("center", (0.5, 0.5)),
        ("Right", (1.0, 0.5)),
        ("top", (0.5, 0.0)),
        ("bottom", (0.5, 1.0)),
        (0.3, (0.3, 0.5)),
        (1, (1.0, 0.5)),
        ({"x": 0.2}, (0.2, 0.5)),
        ({"y": "bottom"}, (0.5, 1.0)),
        ({"x": "right", "y": 0.4}, (1.0, 0.4)),
    ],
)
def test_focus_spec_parse(value, expected) -> None:
    focus = SceneSpec(id="s", image="a.png", focus=value).focus
    assert (focus.x, focus.y) == expected


def test_focus_default_is_none() -> None:
    assert SceneSpec(id="s", image="a.png").focus is None


@pytest.mark.parametrize(
    "value",
    [1.5, -0.1, "middle", True, {"x": "top"}, {"y": "left"}, {"z": 0.1}, [0.1, 0.2]],
)
def test_focus_spec_invalid(value) -> None:
    with pytest.raises(ValueError):
        FocusSpec.model_validate(value)
