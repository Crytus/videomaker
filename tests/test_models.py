from pathlib import Path
import pytest
from pydantic import ValidationError
from videomaker.models import SceneSpec

def test_scene_image_only():
    scene = SceneSpec(
        id="s1",
        image=Path("img.jpg"),
        duration=5,
        voiceover="test"
    )
    assert scene.image == Path("img.jpg")
    assert scene.video is None

def test_scene_video_only():
    scene = SceneSpec(
        id="s2",
        video=Path("vid.mp4"),
        duration=5,
        voiceover="test"
    )
    assert scene.video == Path("vid.mp4")
    assert scene.image is None

def test_scene_both_error():
    with pytest.raises(ValidationError) as exc:
        SceneSpec(
            id="s3",
            image=Path("img.jpg"),
            video=Path("vid.mp4"),
            duration=5,
            voiceover="test"
        )
    assert "image と video は同時に指定できません" in str(exc.value)

def test_scene_neither_error():
    with pytest.raises(ValidationError) as exc:
        SceneSpec(
            id="s4",
            duration=5,
            voiceover="test"
        )
    assert "image または video のいずれかが必要です" in str(exc.value)
