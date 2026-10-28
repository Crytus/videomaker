"""シーンの長さと開始時刻を決める処理。

シーンの長さは次の優先順で決める。
1. 次のシーンに start があれば、その時刻までの長さ（start が最優先）
2. duration（ナレーションより短ければナレーションの長さまで延長）
3. ナレーションの長さ（前後の無音を含む）＋ 次のシーンへの切り替えの間（interval / video.scene_interval）
4. 動画素材の長さ
5. 最後のシーンでBGMがあれば、BGMの終わりまで
"""

from __future__ import annotations

from typing import Sequence


from .errors import ScriptError
from .models import SceneSpec
from .runlog import console


def resolve_durations(
    scenes: Sequence[SceneSpec],
    narration: dict[str, float] | None = None,
    media: dict[str, float] | None = None,
    bgm_remaining: float | None = None,
    default_interval: float = 0.0,
) -> list[float]:
    """全シーンの scene.duration を決め、各シーンの開始時刻（動画の先頭からの秒数）を返す。

    narration: シーンID → ナレーションに必要な長さ（前後の無音を含む）
    media: シーンID → 動画素材の長さ
    bgm_remaining: 動画の先頭から見たBGMの残りの長さ（BGMが無ければNone）
    default_interval: ナレーションが終わってから次のシーンに切り替わるまでの間の既定値（video.scene_interval）

    開始時刻はクロスフェードによる重なりを考えない目安の値で、
    start を指定したシーンだけは正確な時刻になる。
    """
    narration = narration or {}
    media = media or {}
    starts: list[float] = []
    current = 0.0
    for i, scene in enumerate(scenes):
        start = scene.start if scene.start is not None else current
        starts.append(start)
        next_scene = scenes[i + 1] if i + 1 < len(scenes) else None
        needed = narration.get(scene.id, 0.0)

        if next_scene is not None and next_scene.start is not None:
            # 次のシーンの開始時刻までの長さにする（startが最優先）
            duration = next_scene.start - start
            if duration <= 0:
                raise ScriptError(
                    f"シーン {next_scene.id} の start ({next_scene.start:g}秒) が、"
                    f"シーン {scene.id} の開始時刻 ({start:.2f}秒) 以前になっています",
                    hint="前のシーンの duration やナレーションが長すぎないか、start の値を確認してください。",
                )
            if scene.duration is not None and abs(scene.duration - duration) > 0.01:
                console.warn(
                    f"シーン {scene.id} の duration ({scene.duration:g}秒) は、"
                    f"次のシーン {next_scene.id} の start に合わせて {duration:.2f}秒にしました"
                )
            if needed > duration + 0.01:
                console.warn(
                    f"シーン {scene.id} のナレーション（{needed:.2f}秒）が、"
                    f"次のシーン {next_scene.id} の start までの {duration:.2f}秒に収まりません（途中で切れます）"
                )
        elif scene.duration is not None:
            duration = scene.duration
            if needed > duration + 0.01:
                console.warn(
                    f"シーン {scene.id} のduration ({duration:.2f}秒) がナレーション"
                    f"（前後の無音を含めて {needed:.2f}秒）より短いため、{needed:.2f}秒に延長しました"
                )
                duration = needed
        elif needed > 0:
            duration = needed
            # 次のシーンに切り替わる前に間をあける（最後のシーンは切り替えが無いので加えない）
            interval = scene.interval if scene.interval is not None else default_interval
            if next_scene is not None and interval > 0:
                duration += interval
        elif scene.id in media:
            duration = media[scene.id]
        elif next_scene is None and bgm_remaining is not None:
            # 最後のシーンはBGMの終わりまで表示する
            duration = bgm_remaining - start
            if duration <= 0:
                raise ScriptError(
                    f"最後のシーン {scene.id} の開始時刻 ({start:.2f}秒) がBGMの終わりより後です",
                    hint="start の値か、video.bgm_start を確認してください。",
                )
            console.log(f"[cyan]最後のシーン {scene.id} をBGMの終わりまで表示します（{duration:.2f}秒）[/]")
        else:
            hint = (
                "duration を指定するか、voiceover を書いてください。"
                if next_scene is not None
                else "duration を指定するか、voiceover を書くか、BGMを指定してください（BGMの終わりまで表示します）。"
            )
            if next_scene is not None:
                hint += f"次のシーン {next_scene.id} に start を指定しても長さが決まります。"
            raise ScriptError(f"シーン {scene.id} の長さが決まりません", hint=hint)

        scene.duration = duration
        current = start + duration
    return starts
