"""シーン切り替えのトランジション（cut / fade / crossfade）。

高速化のため、MoviePyの毎フレーム合成（CompositeVideoClip）は使わず、
トランジション区間だけnumpyでフレームを混ぜる。それ以外の区間は
各シーンのフレームをそのまま返すので、静止画シーンの高速化（_freeze_static）が効いたままになる。
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from rich.console import Console

from .models import SceneSpec, VideoSpec

console = Console()

# これより短くしか取れないトランジションはカットにする（秒）
MIN_TRANSITION = 0.05

TRANSITION_NAMES = {"fade": "フェード", "crossfade": "クロスフェード"}


@dataclass
class Transition:
    """前のシーンからあるシーンへの切り替え方。"""

    kind: str = "cut"
    duration: float = 0.0

    @property
    def overlap(self) -> float:
        """前後のシーンが重なる時間。重なるのはクロスフェードだけ。"""
        return self.duration if self.kind == "crossfade" else 0.0


# ナレーションが鳴っている区間（シーン内の開始秒, 終了秒）。音声が無いシーンはNone
SpeechSpan = tuple[float, float] | None


def plan_transitions(
    scenes: Sequence[SceneSpec],
    video: VideoSpec,
    speech: dict[str, SpeechSpan] | None = None,
) -> list[Transition]:
    """シーン境界ごとのトランジションを決める。

    戻り値の[i]はシーンi-1からシーンiへの切り替え（[0]は常にcut）。
    - 長さは前後どちらのシーンの半分も超えないようにする（前後のトランジションが重ならないように）。
    - クロスフェードは、前のシーンの末尾の無音＋次のシーンの先頭の無音を超えると
      ナレーションが重なるので、その範囲まで短縮する。
    """
    speech = speech or {}
    plans = [Transition()]
    for prev, scene in zip(scenes, scenes[1:]):
        kind = scene.transition or video.transition
        duration = scene.transition_duration or video.transition_duration
        if kind == "cut":
            plans.append(Transition())
            continue

        allowed = min(prev.duration, scene.duration) / 2
        reason = "シーンが短いため"
        if kind == "crossfade":
            silent = _silent_tail(prev, speech.get(prev.id)) + _silent_head(scene, speech.get(scene.id))
            if silent < allowed:
                allowed = silent
                reason = "ナレーションの重なりを避けるため"

        name = TRANSITION_NAMES.get(kind, kind)
        if duration > allowed:
            if allowed < MIN_TRANSITION:
                console.log(f"[yellow]シーン {scene.id} への{name}をカットに変更しました（{reason}）[/]")
                plans.append(Transition())
                continue
            console.log(
                f"[yellow]シーン {scene.id} への{name}を {duration:.2f}秒 → {allowed:.2f}秒に短縮しました（{reason}）[/]"
            )
            duration = allowed
        plans.append(Transition(kind, duration))
    return plans


def _silent_tail(scene: SceneSpec, span: SpeechSpan) -> float:
    """シーン末尾の、ナレーションが鳴っていない時間。"""
    if span is None:
        return scene.duration
    return max(scene.duration - span[1], 0.0)


def _silent_head(scene: SceneSpec, span: SpeechSpan) -> float:
    """シーン先頭の、ナレーションが鳴っていない時間。"""
    if span is None:
        return scene.duration
    return min(max(span[0], 0.0), scene.duration)


def scene_starts(durations: Sequence[float], plans: Sequence[Transition]) -> list[float]:
    """各シーンの開始時刻。クロスフェードの分だけ前のシーンに重ねる。"""
    starts = []
    current = 0.0
    for i, duration in enumerate(durations):
        if i > 0:
            current -= plans[i].overlap
        starts.append(current)
        current += duration
    return starts


def compose_timeline(clips: Sequence, plans: Sequence[Transition], video_clip_cls, audio_clip_cls):
    """シーンのクリップをトランジション付きで1本の動画にする。

    video_clip_cls / audio_clip_cls にはMoviePyの VideoClip / CompositeAudioClip を渡す。
    戻り値は (動画クリップ, 各シーンの開始時刻のリスト)。
    """
    durations = [clip.duration for clip in clips]
    starts = scene_starts(durations, plans)
    total = starts[-1] + durations[-1]
    count = len(clips)

    def scene_frame(i: int, local: float) -> np.ndarray:
        # 浮動小数の誤差でクリップ末尾を超えないようにする
        local = min(max(local, 0.0), max(durations[i] - 1e-3, 0.0))
        frame = clips[i].get_frame(local)
        factor = 1.0
        fade_in = plans[i]
        if fade_in.kind == "fade":
            half = fade_in.duration / 2
            factor = min(factor, local / half)
        if i + 1 < count and plans[i + 1].kind == "fade":
            half = plans[i + 1].duration / 2
            factor = min(factor, (durations[i] - local) / half)
        if factor < 1.0:
            frame = (frame.astype(np.float32) * max(factor, 0.0)).astype(np.uint8)
        return frame

    def frame_function(t: float) -> np.ndarray:
        i = min(max(bisect.bisect_right(starts, t) - 1, 0), count - 1)
        local = t - starts[i]
        frame = scene_frame(i, local)
        plan = plans[i]
        if plan.kind == "crossfade" and local < plan.duration:
            # 前のシーンに重なっている区間は2つのフレームを混ぜる
            alpha = local / plan.duration
            prev = scene_frame(i - 1, t - starts[i - 1])
            frame = (prev.astype(np.float32) * (1.0 - alpha) + frame.astype(np.float32) * alpha).astype(
                np.uint8
            )
        return frame

    timeline = video_clip_cls(frame_function=frame_function, duration=total)

    audio_parts = []
    for clip, start in zip(clips, starts):
        if clip.audio is None:
            continue
        audio = clip.audio
        # シーンより長い音声が次のシーンに食い込まないよう切り詰める
        if audio.duration is not None and audio.duration > clip.duration:
            audio = audio.subclipped(0, clip.duration)
        audio_parts.append(audio.with_start(start))
    if audio_parts:
        timeline = timeline.with_audio(audio_clip_cls(audio_parts).with_duration(total))
    return timeline, starts
