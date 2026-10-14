"""素材と出力のアスペクト比が違うときに、変形せず中央を切り取ることのテスト。"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

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
