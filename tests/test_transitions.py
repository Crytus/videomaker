"""シーン切り替えのトランジションのテスト。"""

import wave
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from videomaker.config import AppConfig
from videomaker.models import VideoScript
from videomaker.renderer import Renderer, RenderSettings
from videomaker.transitions import Transition, compose_timeline, plan_transitions, scene_starts


def _script(scenes: list[dict], **video) -> VideoScript:
    return VideoScript.model_validate({"video": video, "scenes": scenes})


def _scene(scene_id: str, duration: float, **extra) -> dict:
    return {"id": scene_id, "image": "a.png", "duration": duration, "voiceover": "x", **extra}


# ---- トランジションの決定 ----

def test_default_is_cut() -> None:
    script = _script([_scene("a", 4), _scene("b", 4)])
    plans = plan_transitions(script.scenes, script.video)
    assert [p.kind for p in plans] == ["cut", "cut"]


def test_video_default_and_scene_override() -> None:
    script = _script(
        [_scene("a", 4), _scene("b", 4), _scene("c", 4, transition="cut"),
         _scene("d", 4, transition="crossfade", transition_duration=1.0)],
        transition="fade", transition_duration=0.6,
    )
    plans = plan_transitions(script.scenes, script.video)
    assert [(p.kind, p.duration) for p in plans] == [
        ("cut", 0.0), ("fade", 0.6), ("cut", 0.0), ("crossfade", 1.0)
    ]


def test_crossfade_shortened_to_avoid_voice_overlap() -> None:
    script = _script([_scene("a", 4), _scene("b", 4)], transition="crossfade", transition_duration=1.5)
    # aは3.7秒まで、bは0.5秒から話す -> 無音は 0.3 + 0.5 = 0.8秒
    speech = {"a": (0.2, 3.7), "b": (0.5, 3.0)}
    plans = plan_transitions(script.scenes, script.video, speech)
    assert plans[1].kind == "crossfade"
    assert plans[1].duration == pytest.approx(0.8)


def test_crossfade_without_voice_is_not_shortened() -> None:
    script = _script([_scene("a", 4), _scene("b", 4)], transition="crossfade", transition_duration=1.5)
    plans = plan_transitions(script.scenes, script.video, {"a": None, "b": None})
    assert plans[1].duration == pytest.approx(1.5)


def test_transition_limited_by_scene_length() -> None:
    script = _script([_scene("a", 1.0), _scene("b", 4)], transition="fade", transition_duration=2.0)
    plans = plan_transitions(script.scenes, script.video)
    assert plans[1].duration == pytest.approx(0.5)


def test_crossfade_falls_back_to_cut() -> None:
    script = _script([_scene("a", 4), _scene("b", 4)], transition="crossfade")
    # 前後に無音がまったく無い
    plans = plan_transitions(script.scenes, script.video, {"a": (0.0, 4.0), "b": (0.0, 4.0)})
    assert plans[1].kind == "cut"


def test_scene_starts_with_overlap() -> None:
    plans = [Transition(), Transition("crossfade", 1.0), Transition("fade", 0.5)]
    assert scene_starts([4.0, 3.0, 2.0], plans) == [0.0, 3.0, 6.0]


# ---- フレームの合成 ----

class _SolidClip:
    """単色フレームを返すだけのテスト用クリップ。"""

    def __init__(self, value: int, duration: float) -> None:
        self.value = value
        self.duration = duration
        self.audio = None

    def get_frame(self, t: float) -> np.ndarray:
        assert 0.0 <= t <= self.duration
        return np.full((4, 4, 3), self.value, dtype=np.uint8)


def _timeline(plans):
    from moviepy import CompositeAudioClip, VideoClip

    clips = [_SolidClip(200, 4.0), _SolidClip(100, 4.0)]
    return compose_timeline(clips, plans, VideoClip, CompositeAudioClip)


def test_crossfade_frames() -> None:
    clip, starts = _timeline([Transition(), Transition("crossfade", 1.0)])
    assert starts == [0.0, 3.0]
    assert clip.duration == pytest.approx(7.0)
    assert clip.get_frame(2.0)[0, 0, 0] == 200
    assert clip.get_frame(3.5)[0, 0, 0] == pytest.approx(150, abs=1)  # 中間で半々に混ざる
    assert clip.get_frame(5.0)[0, 0, 0] == 100


def test_fade_frames() -> None:
    clip, starts = _timeline([Transition(), Transition("fade", 1.0)])
    assert starts == [0.0, 4.0]
    assert clip.duration == pytest.approx(8.0)
    assert clip.get_frame(3.0)[0, 0, 0] == 200
    assert clip.get_frame(3.75)[0, 0, 0] == pytest.approx(100, abs=1)  # 暗くなる途中
    assert clip.get_frame(4.0)[0, 0, 0] == 0  # 切り替わりの瞬間は黒
    assert clip.get_frame(4.25)[0, 0, 0] == pytest.approx(50, abs=1)  # 明るくなる途中
    assert clip.get_frame(5.0)[0, 0, 0] == 100


# ---- 実際の書き出し ----

def _wav(path: Path, seconds: float) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x10\x00" * int(24000 * seconds))
    return path


def test_render_crossfade(tmp_path: Path) -> None:
    Image.new("RGB", (64, 48), (255, 0, 0)).save(tmp_path / "red.png")
    Image.new("RGB", (64, 48), (0, 0, 255)).save(tmp_path / "blue.png")
    script = VideoScript.model_validate({
        "video": {"width": 64, "height": 48, "fps": 10,
                  "transition": "crossfade", "transition_duration": 1.0},
        "scenes": [
            {"id": "a", "image": str(tmp_path / "red.png"), "duration": 3.0, "voiceover": "", "subtitle": ""},
            {"id": "b", "image": str(tmp_path / "blue.png"), "duration": 3.0, "voiceover": "", "subtitle": ""},
        ],
    })
    # 音声: 前の無音0.5秒 + 2.0秒 -> aの末尾0.5秒 + bの先頭0.5秒 = 1.0秒までは重ならない
    audio_map = {"a": _wav(tmp_path / "a.wav", 2.0), "b": _wav(tmp_path / "b.wav", 2.0)}
    config = AppConfig(voice_margin_before=0.5, video_encoder="cpu")
    renderer = Renderer(script, config=config, settings=RenderSettings(encoder="cpu"))
    out = renderer.render(output_path=tmp_path / "out.mp4", scene_ids=None, audio_map=audio_map)

    assert [(s.id, start, end) for s, start, end, _ in renderer.timeline] == [
        ("a", 0.0, 3.0), ("b", 2.0, 5.0)
    ]

    from moviepy import VideoFileClip

    clip = VideoFileClip(str(out))
    try:
        assert clip.duration == pytest.approx(5.0, abs=0.2)
        assert clip.audio is not None
        red, _, blue = clip.get_frame(2.5)[24, 32].astype(int)
        # クロスフェードの途中は赤と青が混ざる
        assert 60 < red < 200 and 60 < blue < 200
    finally:
        clip.close()


def test_subtitle_window(tmp_path: Path) -> None:
    script = _script([_scene("a", 4.0, voiceover="一行目\n二行目")])
    renderer = Renderer(script, config=AppConfig(subtitle_line_interval=0.0))
    clips = renderer._create_subtitle_clip(script.scenes[0], text="一行目\n二行目", window=(1.0, 3.0))
    assert [(c.start, c.end) for c in clips] == [(1.0, 2.0), (2.0, 3.0)]
