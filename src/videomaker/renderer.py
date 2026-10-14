"""MoviePyベースの簡易レンダラー。"""

from __future__ import annotations

import bisect
import functools
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image

try:
    # MoviePy 2.x
    from moviepy import (
        AudioClip,
        AudioFileClip,
        CompositeAudioClip,
        CompositeVideoClip,
        ImageClip,
        TextClip,
        VideoClip,
        VideoFileClip,
        concatenate_audioclips,
        concatenate_videoclips,
    )
    from moviepy.audio.fx import AudioFadeIn, AudioFadeOut, AudioLoop
    from moviepy.video.fx import Loop
    MOVIEPY_VERSION = 2
except ImportError:
    # MoviePy 1.x fallback
    from moviepy.editor import (
        AudioFileClip,
        CompositeAudioClip,
        CompositeVideoClip,
        ImageClip,
        TextClip,
        VideoFileClip,
        concatenate_audioclips,
        concatenate_videoclips,
    )
    MOVIEPY_VERSION = 1
from rich.console import Console

from .config import AppConfig
from .errors import AssetError, RenderError, VideoMakerError
from .models import SceneSpec, SubtitleStyle, VideoScript, parse_color
from .textsplit import split_text_lines
from .transitions import SpeechSpan, Transition, compose_timeline, fit_to_starts, plan_transitions

console = Console()


@dataclass
class RenderSettings:
    """書き出し時のフレームレート・解像度・エンコーダ設定。"""

    preview: bool = False  # 速度優先のエンコード設定を使う
    fps: int | None = None  # Noneならスクリプトのfps
    scale: float = 1.0  # 出力解像度の倍率（プレビュー用）
    encoder: str = "auto"
    preset: str | None = None
    quality: int | None = None

    @classmethod
    def from_config(cls, config: AppConfig | None, *, preview: bool = False) -> "RenderSettings":
        if config is None:
            config = AppConfig()
        settings = cls(
            encoder=config.video_encoder,
            preset=config.video_preset,
            quality=config.video_quality,
        )
        if preview:
            settings.preview = True
            settings.fps = config.preview_fps
            settings.scale = config.preview_scale
        return settings


@functools.lru_cache(maxsize=None)
def _nvenc_available() -> bool:
    """同梱FFmpegでh264_nvencが実際に動作するか確認する。"""
    try:
        from moviepy.config import FFMPEG_BINARY

        result = subprocess.run(
            [
                FFMPEG_BINARY, "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1",
                "-c:v", "h264_nvenc", "-f", "null", "-",
            ],
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


def _resolve_codec(encoder: str) -> str:
    name = encoder.lower()
    if name == "cpu":
        return "libx264"
    if name in ("nvenc", "gpu"):
        if not _nvenc_available():
            console.log("[yellow]NVENCが利用できないため、libx264(CPU)でエンコードします[/]")
            return "libx264"
        return "h264_nvenc"
    if name == "auto":
        return "h264_nvenc" if _nvenc_available() else "libx264"
    return encoder


class Renderer:
    """シーン定義と音声クリップを使って動画を書き出す。"""

    def __init__(
        self,
        script: VideoScript,
        config: AppConfig | None = None,
        settings: RenderSettings | None = None,
        no_voice: bool = False,
        line_timings: dict[str, list[tuple[float, float]]] | None = None,
        start_offset: float = 0.0,
    ) -> None:
        self.script = script
        self.config = config
        self.settings = settings or RenderSettings.from_config(config)
        # 音声なしモード（アフレコ用）では音声が無いことを警告しない
        self.no_voice = no_voice
        # シーンごとの各行の音声が鳴る区間。あれば字幕をナレーションに合わせて表示する
        self.line_timings = line_timings or {}
        # 書き出す最初のシーンの、本来の動画での開始時刻（--scene で途中から書き出すときにBGMの位置を合わせる）
        self.start_offset = start_offset
        # 書き出したシーンの (シーン, 開始秒, 終了秒, そのシーンへの切り替え)。アフレコ用タイムテーブルに使う
        self.timeline: list[tuple[SceneSpec, float, float, Transition]] = []
        # 書き出し中に開いた素材ファイル（ffmpegの読み込みプロセスを持つ）。書き出し後にまとめて閉じる
        self._opened_media: list = []

    def render(
        self,
        *,
        output_path: Path,
        scene_ids: Iterable[str] | None,
        audio_map: dict[str, Path],
    ) -> Path:
        try:
            return self._render(output_path=output_path, scene_ids=scene_ids, audio_map=audio_map)
        finally:
            # 開いた素材を明示的に閉じる。閉じずにおくと、Python終了時のガベージコレクションで
            # ffmpegプロセスを片付けようとして「ハンドルが無効です」(WinError 6) が表示されることがある
            self._close_opened_media()

    def _open_media(self, loader, scene_id: str, kind: str, path: Path):
        """素材ファイルを読み込み、書き出し後に閉じられるよう記録する。"""
        clip = _load_media(loader, scene_id, kind, path)
        self._opened_media.append(clip)
        return clip

    def _close_opened_media(self) -> None:
        for clip in self._opened_media:
            try:
                clip.close()
            except (OSError, AttributeError):
                pass  # クローズ時のエラーは無視
        self._opened_media.clear()

    def _render(
        self,
        *,
        output_path: Path,
        scene_ids: Iterable[str] | None,
        audio_map: dict[str, Path],
    ) -> Path:
        scenes = self._select_scenes(scene_ids)
        for scene in scenes:
            if scene.duration is None:
                raise RenderError(
                    f"シーン {scene.id} の長さが決まりません",
                    hint="duration を指定するか、voiceover の音声が生成されるようにしてください。",
                )

        # 字幕の表示区間を決めるため、クリップを作る前にトランジションを決める
        plans = plan_transitions(scenes, self.script.video, self._speech_spans(scenes, audio_map))
        # startを指定したシーンが指定時刻に始まるよう、クロスフェードの重なりを考えて直前のシーンの長さを直す
        fixed_starts = self._fixed_starts(scenes)
        durations = fit_to_starts([scene.duration for scene in scenes], plans, fixed_starts)
        for scene, duration in zip(scenes, durations):
            scene.duration = duration
        clips: list[VideoClip] = []
        for i, scene in enumerate(scenes):
            # クロスフェードで前後のシーンと重なる区間は字幕を出さない
            next_overlap = plans[i + 1].overlap if i + 1 < len(scenes) else 0.0
            clip = self._build_scene_clip(
                scene, audio_map, subtitle_window=(plans[i].overlap, scene.duration - next_overlap)
            )
            next_fixed = i + 1 < len(scenes) and fixed_starts[i + 1] is not None
            if next_fixed and abs(clip.duration - scene.duration) > 1e-3:
                # 次のシーンの開始時刻がずれないよう、動画素材の長さではなく決めた長さにそろえる
                clip = clip.with_duration(scene.duration)
            clips.append(clip)

        # 毎フレーム合成（"compose"連結）は遅いので、トランジション区間だけ混ぜる独自の連結を使う
        final, starts = compose_timeline(clips, plans, VideoClip, CompositeAudioClip)
        self.timeline = [
            (scene, start, start + clip.duration, plan)
            for scene, start, clip, plan in zip(scenes, starts, clips, plans)
        ]
        final = self._apply_bgm(final)

        fps = self.settings.fps or self.script.video.fps
        codec = _resolve_codec(self.settings.encoder)
        preset, ffmpeg_params = self._encoder_options(codec)

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RenderError(f"出力先ディレクトリを作成できません: {output_path.parent} ({exc})") from exc
        console.log(f"動画を書き出し中: {output_path} (codec={codec}, fps={fps}, scale={self.settings.scale})")
        try:
            final.write_videofile(
                filename=str(output_path),
                fps=fps,
                codec=codec,
                preset=preset,
                audio_codec="aac",
                ffmpeg_params=ffmpeg_params,
            )
        except PermissionError as exc:
            raise RenderError(
                f"出力ファイルに書き込めません: {output_path}",
                hint="動画プレーヤーなどでファイルを開いていないか確認してください。",
            ) from exc
        except Exception as exc:
            raise RenderError(
                f"動画の書き出しに失敗しました: {output_path}\n  {_first_line(exc)}",
                hint=f"エンコーダ({codec})で失敗する場合は --encoder cpu を試してください。"
                "出力先の空き容量や書き込み権限も確認してください。",
            ) from exc

        # クリップを安全にクローズ
        for clip in clips:
            try:
                clip.close()
            except (OSError, AttributeError):
                pass  # クローズ時のエラーは無視
        try:
            final.close()
        except (OSError, AttributeError):
            pass
        return output_path

    def _encoder_options(self, codec: str) -> tuple[str, list[str]]:
        """エンコーダごとのプリセットと追加のFFmpeg引数を返す。"""
        preview = self.settings.preview
        params: list[str] = []
        if codec == "h264_nvenc":
            preset = self.settings.preset or ("p1" if preview else "p5")
            quality = self.settings.quality or (32 if preview else 23)
            params += ["-rc", "vbr", "-cq", str(quality), "-b:v", "0"]
        elif codec == "libx264":
            preset = self.settings.preset or ("ultrafast" if preview else "medium")
            quality = self.settings.quality or (30 if preview else 23)
            params += ["-crf", str(quality), "-tune", "stillimage"]
        else:
            preset = self.settings.preset or "medium"

        return preset, params

    def _output_size(self) -> tuple[int, int]:
        """書き出し解像度（プレビュー時は縮小、偶数に丸める）。"""
        width, height = self.script.video.width, self.script.video.height
        if self.settings.scale >= 1.0:
            return width, height
        return (
            max(2, int(width * self.settings.scale) // 2 * 2),
            max(2, int(height * self.settings.scale) // 2 * 2),
        )

    def _select_scenes(self, scene_ids: Iterable[str] | None) -> list[SceneSpec]:
        if not scene_ids:
            return list(self.script.scenes)
        allowed = set(scene_ids)
        selected = [scene for scene in self.script.scenes if scene.id in allowed]
        if not selected:
            available = ", ".join(scene.id for scene in self.script.scenes)
            raise VideoMakerError(
                f"指定されたシーンが見つかりません: {', '.join(allowed)}",
                hint=f"指定できるシーンID: {available}",
            )
        return selected

    def _fixed_starts(self, scenes: list[SceneSpec]) -> list[float | None]:
        """各シーンの、書き出す動画の先頭から見た開始時刻（startが無ければNone）。

        --scene で飛び飛びに選んだ場合、間のシーンが抜けた箇所より後ろは開始時刻を合わせない。
        """
        index = {scene.id: i for i, scene in enumerate(self.script.scenes)}
        fixed: list[float | None] = [None]
        contiguous = True
        for prev, scene in zip(scenes, scenes[1:]):
            contiguous = contiguous and index[scene.id] == index[prev.id] + 1
            if scene.start is not None and contiguous:
                fixed.append(scene.start - self.start_offset)
            else:
                fixed.append(None)
        return fixed

    def _speech_spans(self, scenes: list[SceneSpec], audio_map: dict[str, Path]) -> dict[str, SpeechSpan]:
        """各シーンでナレーションが鳴る区間（シーン内の開始秒, 終了秒）を求める。"""
        margin_before = self.config.voice_margin_before if self.config else 0.0
        spans: dict[str, SpeechSpan] = {}
        for scene in scenes:
            audio_path = audio_map.get(scene.id)
            if not audio_path or not audio_path.exists():
                spans[scene.id] = None
                continue
            audio = _load_media(lambda: AudioFileClip(str(audio_path)), scene.id, "音声", audio_path)
            try:
                spans[scene.id] = (margin_before, margin_before + audio.duration)
            finally:
                audio.close()
        return spans

    def _build_scene_clip(
        self,
        scene: SceneSpec,
        audio_map: dict[str, Path],
        subtitle_window: tuple[float, float] | None = None,
    ) -> VideoClip:
        """シーンのクリップを作る。subtitle_windowは字幕を表示する区間（シーン内の開始秒, 終了秒）。"""
        if scene.image:
            clip = _load_media(
                lambda: ImageClip(str(scene.image), duration=scene.duration).resized(
                    (self.script.video.width, self.script.video.height)
                ),
                scene.id, "画像", scene.image,
            )
        elif scene.video:
            clip = self._open_media(lambda: VideoFileClip(str(scene.video)), scene.id, "動画", scene.video)
            # リサイズ
            clip = clip.resized((self.script.video.width, self.script.video.height))
            # 長さ調整: 指定時間と実際の長さの差が5%以内の場合は実際の長さを使用
            duration_diff = abs(clip.duration - scene.duration)
            if duration_diff / scene.duration <= 0.05:
                # 5%以内の差なら、実際のクリップの長さをそのまま使用
                console.log(f"[cyan]ビデオの長さ ({clip.duration}秒) を使用します (指定: {scene.duration}秒)[/]")
                pass
            elif clip.duration < scene.duration:
                # 短い場合は指定された長さでカット（最後のフレームを保持）
                console.log(f"[yellow]ビデオが短いため、{scene.duration}秒にトリミングします（実際: {clip.duration}秒）[/]")
                clip = clip.with_duration(scene.duration)
            else:
                # 長い場合はカット
                console.log(f"[cyan]ビデオを{scene.duration}秒にカットします（実際: {clip.duration}秒）[/]")
                clip = clip.subclipped(0, scene.duration)
        else:
            raise ValueError(f"シーン {scene.id} には image または video が必要です")

        audio_path = audio_map.get(scene.id)
        if audio_path and audio_path.exists():
            voice = self._open_media(lambda: AudioFileClip(str(audio_path)), scene.id, "音声", audio_path)

            # 音量を調整（個別設定 > config > デフォルト）
            volume = (
                scene.voice_override.volume if scene.voice_override and scene.voice_override.volume is not None
                else (self.config.voice_volume if self.config else 1.0)
            )
            if volume != 1.0:
                voice = voice.with_volume_scaled(volume)
                console.log(f"[cyan]音量を調整: {scene.id} -> {volume * 100:.0f}%[/]")

            # 音声の前後に無音を追加
            margin_before = self.config.voice_margin_before if self.config else 0.0
            margin_after = self.config.voice_margin_after if self.config else 0.0

            if margin_before > 0 or margin_after > 0:
                audio_clips = []

                # 前の無音
                if margin_before > 0:
                    silence_before = AudioClip(lambda t: 0, duration=margin_before, fps=voice.fps or 44100)
                    audio_clips.append(silence_before)
                    console.log(f"[cyan]音声の前に {margin_before}秒の無音を追加: {scene.id}[/]")

                # 元の音声
                audio_clips.append(voice)

                # 後の無音
                if margin_after > 0:
                    silence_after = AudioClip(lambda t: 0, duration=margin_after, fps=voice.fps or 44100)
                    audio_clips.append(silence_after)
                    console.log(f"[cyan]音声の後に {margin_after}秒の無音を追加: {scene.id}[/]")

                # 連結
                voice = concatenate_audioclips(audio_clips)

            clip = clip.with_audio(voice)
        elif not self.no_voice and scene.voiceover.strip():
            console.log(f"[yellow]音声が見つかりません: {scene.id}[/]")

        # テキストオーバーレイを追加
        overlays = [clip]

        # 字幕を追加
        # subtitle未指定（None）の場合はvoiceoverを使用、空文字列の場合は非表示
        if scene.subtitle is None:
            # subtitleが未指定の場合、voiceoverを字幕として使用
            subtitle_clips = self._create_subtitle_clip(
                scene, text=scene.voiceover, window=subtitle_window, timings=self.line_timings.get(scene.id)
            )
            if subtitle_clips:
                # 複数行の場合はリストで返される
                if isinstance(subtitle_clips, list):
                    overlays.extend(subtitle_clips)
                else:
                    overlays.append(subtitle_clips)
        elif scene.subtitle:
            # subtitleが指定されている場合（空文字列でない場合）
            subtitle_clips = self._create_subtitle_clip(scene, text=scene.subtitle, window=subtitle_window)
            if subtitle_clips:
                # 複数行の場合はリストで返される
                if isinstance(subtitle_clips, list):
                    overlays.extend(subtitle_clips)
                else:
                    overlays.append(subtitle_clips)
        # else: scene.subtitle == "" の場合は字幕を表示しない

        # テロップを追加
        if scene.teletext:
            console.log(f"[cyan]シーン {scene.id} にテロップが設定されています[/]")
            teletext_clip = self._create_teletext_clip(scene)
            if teletext_clip:
                # 背景付きの場合は [背景, 文字] のリストで返される
                if isinstance(teletext_clip, list):
                    overlays.extend(teletext_clip)
                else:
                    overlays.append(teletext_clip)
                console.log(f"[green]テロップをオーバーレイに追加しました: {scene.id}[/]")
            else:
                console.log(f"[yellow]テロップクリップの作成に失敗しました: {scene.id}[/]")

        # 合成は元解像度で行い、縮小は最後にかける（字幕位置などのレイアウトを崩さないため）
        output_size = self._output_size()
        if len(overlays) > 1:
            clip = CompositeVideoClip(overlays)
        if scene.image:
            clip = self._freeze_static(clip, overlays[1:], output_size)
        elif output_size != clip.size:
            clip = clip.resized(output_size)

        # "chain"連結でRGBA書き出しにならないようマスクを外す（以前の"compose"と同じく黒背景扱い）
        if clip.mask is not None:
            clip = clip.without_mask()
        return clip

    def _freeze_static(self, clip, overlays, output_size: tuple[int, int]) -> VideoClip:
        """静止画シーンを、字幕の切り替わり区間ごとに1回だけ合成するクリップに置き換える。

        静止画シーンの画面は字幕・テロップの表示開始/終了時刻でしか変化しないため、
        区間ごとに合成したフレームを使い回しても出力は同じになる。
        書き出しはフレーム順に進むので、直前の1フレームだけ保持する。
        """
        duration = clip.duration
        bounds = {0.0, duration}
        for overlay in overlays:
            for t in (overlay.start, overlay.end):
                if t is not None and 0.0 < t < duration:
                    bounds.add(t)
        edges = sorted(bounds)
        cache: dict[int, object] = {}

        def frame_function(t):
            index = min(max(bisect.bisect_right(edges, t) - 1, 0), len(edges) - 2)
            if index not in cache:
                cache.clear()
                frame = clip.get_frame((edges[index] + edges[index + 1]) / 2)
                if (frame.shape[1], frame.shape[0]) != output_size:
                    frame = np.asarray(
                        Image.fromarray(frame).resize(output_size, Image.Resampling.LANCZOS)
                    )
                cache[index] = frame
            return cache[index]

        frozen = VideoClip(frame_function=frame_function, duration=duration)
        if clip.audio is not None:
            frozen = frozen.with_audio(clip.audio)
        return frozen

    def _create_subtitle_clip(
        self,
        scene: SceneSpec,
        text: str,
        window: tuple[float, float] | None = None,
        timings: list[tuple[float, float]] | None = None,
    ):
        """字幕クリップを作成する。複数行の場合はリストで返す。

        windowを指定すると、その区間（シーン内の開始秒, 終了秒）だけに字幕を表示する。
        timingsに各行の音声が鳴る区間を渡すと、字幕をナレーションに合わせて切り替える。
        """
        try:
            window_start, window_end = window or (0.0, scene.duration)
            window_length = window_end - window_start
            if window_length <= 0:
                return None
            subtitle_config = self.script.video.subtitle
            font = self._resolve_font(subtitle_config.font)

            # スタイル設定の解決（個別設定 > config > デフォルト）
            font_size = (
                subtitle_config.style.font_size
                or (self.config.subtitle_font_size if self.config else None)
                or 48
            )
            color = subtitle_config.style.fill
            stroke_color = subtitle_config.style.stroke
            stroke_width = (
                subtitle_config.style.stroke_width
                if subtitle_config.style.stroke_width is not None
                else (self.config.subtitle_stroke_width if self.config else 2)
            )
            background_default = self.config.subtitle_background if self.config else None

            # テキストを行ごとに分割（空行は除外。長い行は句読点を優先して自動分割）
            max_chars = self.config.max_line_chars if self.config else 30
            lines = split_text_lines(text, max_chars)
            if not lines:
                return None

            if len(lines) == 1:
                # 単一行の場合は従来通り
                if subtitle_config.position == "top":
                    y_position = 50 + subtitle_config.style.padding
                else:  # bottom
                    y_position = self.script.video.height - 100 - subtitle_config.style.padding

                txt_clip = TextClip(
                    text=lines[0],
                    font=font,
                    font_size=font_size,
                    color=color,
                    stroke_color=stroke_color if stroke_color else None,
                    stroke_width=stroke_width if stroke_color else 0,
                    size=(self.script.video.width - 200, None),
                    duration=window_length,
                ).with_position(("center", y_position)).with_start(window_start)

                console.log(f"[green]字幕を作成しました: {scene.id} (font_size={font_size})[/]")
                box = self._background_box(
                    [(txt_clip, ("center", y_position))], subtitle_config.style, background_default
                )
                return [box, txt_clip] if box else txt_clip
            else:
                # 複数行の場合は1行ずつ順番に表示（リストで返す）
                console.log(f"[cyan]複数行字幕を作成中: {scene.id} - {len(lines)}行（順次表示）[/]")

                clips = []

                # Y位置は固定（1行だけ表示されるため）
                if subtitle_config.position == "top":
                    y_position = 50 + subtitle_config.style.padding
                else:  # bottom
                    y_position = self.script.video.height - 100 - subtitle_config.style.padding

                # 行間の時間間隔を取得
                line_interval = self.config.subtitle_line_interval if self.config else 0.0

                if timings and len(timings) == len(lines):
                    # 各行の音声が鳴る区間に合わせて表示する（最後の行は区間の終わりまで残す）
                    spans = [(start, end) for start, end in timings]
                    spans[-1] = (spans[-1][0], max(spans[-1][1], window_end))
                    console.log(f"[cyan]字幕をナレーションの各行に合わせて表示します: {scene.id}[/]")
                else:
                    # 音声の区切りが分からない場合は、表示区間を文字数（空白を除く）に比例して割り振る
                    total_interval = (len(lines) - 1) * line_interval
                    actual_duration = window_length - total_interval
                    weights = [max(len("".join(line.split())), 1) for line in lines]
                    total_weight = sum(weights)
                    spans = []
                    current = window_start
                    for weight in weights:
                        length = actual_duration * weight / total_weight
                        spans.append((current, current + length))
                        current += length + line_interval

                for i, (line, (span_start, span_end)) in enumerate(zip(lines, spans)):
                    # クロスフェードなどで字幕を出さない区間にかかる部分は削る
                    current_time = max(span_start, window_start)
                    duration_per_line = min(span_end, window_end) - current_time
                    if duration_per_line < 0.05:
                        continue
                    txt_clip = TextClip(
                        text=line,
                        font=font,
                        font_size=font_size,
                        color=color,
                        stroke_color=stroke_color if stroke_color else None,
                        stroke_width=stroke_width if stroke_color else 0,
                        size=(self.script.video.width - 200, None),
                        duration=duration_per_line,
                    ).with_position(("center", y_position)).with_start(current_time)

                    # 背景は行ごとに、その行の文字の大きさに合わせて付ける
                    box = self._background_box(
                        [(txt_clip, ("center", y_position))], subtitle_config.style, background_default
                    )
                    if box:
                        clips.append(box)
                    clips.append(txt_clip)
                    console.log(f"[green]  行{i+1}: '{line}' (開始: {current_time:.2f}秒, 長さ: {duration_per_line:.2f}秒)[/]")

                # 複数のテキストクリップをリストで返す
                if clips:
                    console.log(f"[green]複数行字幕を作成しました: {scene.id} ({len(lines)}行、順次表示)[/]")
                    return clips

                return None
        except Exception as e:
            console.log(f"[yellow]字幕の作成に失敗しました ({scene.id}): {e}[/]")
            import traceback
            console.log(f"[yellow]{traceback.format_exc()}[/]")
            return None

    def _create_teletext_clip(self, scene: SceneSpec):
        """テロップクリップを作成する。複数行の場合は行ごとに分けて表示。"""
        try:
            teletext = scene.teletext
            if not teletext:
                return None

            subtitle_config = self.script.video.subtitle
            font = self._resolve_font(subtitle_config.font)

            # スタイル設定の解決（個別設定 > config > デフォルト）
            font_size = (
                teletext.style.font_size
                or (self.config.teletext_font_size if self.config else None)
                or 60
            )
            color = teletext.style.fill
            stroke_color = teletext.style.stroke
            stroke_width = (
                teletext.style.stroke_width
                if teletext.style.stroke_width is not None
                else (self.config.teletext_stroke_width if self.config else 3)
            )

            # テキストを行ごとに分割
            lines = [line.strip() for line in teletext.text.split('\n') if line.strip()]

            background_default = self.config.teletext_background if self.config else None

            if len(lines) == 1:
                # 単一行の場合は従来通り
                padding = 50
                txt_clip = TextClip(
                    text=lines[0],
                    font=font,
                    font_size=font_size,
                    color=color,
                    stroke_color=stroke_color if stroke_color else None,
                    stroke_width=stroke_width if stroke_color else 0,
                    duration=scene.duration,
                )
                # 右・下寄せは文字の大きさを引いて、画面内に収まる位置にする
                width, height = self.script.video.width, self.script.video.height
                clip_w, clip_h = txt_clip.size
                position_map = {
                    "top_left": (padding, padding),
                    "top_right": (width - padding - clip_w, padding),
                    "bottom_left": (padding, height - padding - clip_h),
                    "bottom_right": (width - padding - clip_w, height - padding - clip_h),
                    "center": ("center", "center"),
                }
                position = position_map.get(teletext.position, ("center", "center"))
                txt_clip = txt_clip.with_position(position)

                console.log(f"[cyan]テロップを作成中: {scene.id} - テキスト='{teletext.text}', 位置={position}, font_size={font_size}[/]")
                console.log(f"[green]テロップを作成しました: {scene.id}[/]")
                box = self._background_box([(txt_clip, position)], teletext.style, background_default)
                return [box, txt_clip] if box else txt_clip
            else:
                # 複数行の場合は行ごとに分けて表示
                console.log(f"[cyan]複数行テロップを作成中: {scene.id} - {len(lines)}行[/]")

                clips = []
                placed = []  # 背景の範囲を求めるための (クリップ, 配置)
                padding = 50
                line_spacing = font_size + 10  # 行間スペース

                # 基準位置を計算
                base_position = teletext.position
                if base_position.startswith("top"):
                    start_y = padding
                elif base_position.startswith("bottom"):
                    start_y = self.script.video.height - padding - (len(lines) * line_spacing)
                else:  # center
                    start_y = (self.script.video.height - (len(lines) * line_spacing)) / 2

                for i, line in enumerate(lines):
                    y_pos = start_y + (i * line_spacing)

                    txt_clip = TextClip(
                        text=line,
                        font=font,
                        font_size=font_size,
                        color=color,
                        stroke_color=stroke_color if stroke_color else None,
                        stroke_width=stroke_width if stroke_color else 0,
                        duration=scene.duration,
                    )
                    if "left" in base_position:
                        x_pos = padding
                    elif "right" in base_position:
                        # 右寄せは各行の右端を揃える
                        x_pos = self.script.video.width - padding - txt_clip.size[0]
                    else:  # center
                        x_pos = "center"
                    txt_clip = txt_clip.with_position((x_pos, y_pos))

                    clips.append(txt_clip)
                    placed.append((txt_clip, (x_pos, y_pos)))
                    console.log(f"[green]  行{i+1}: '{line}' at ({x_pos}, {y_pos})[/]")

                # 複数のテキストクリップを結合（背景は全行をまとめて囲む1枚の矩形）
                if clips:
                    box = self._background_box(placed, teletext.style, background_default)
                    if box:
                        clips.insert(0, box)
                    composite = CompositeVideoClip(clips, size=(self.script.video.width, self.script.video.height))
                    console.log(f"[green]複数行テロップを作成しました: {scene.id} ({len(lines)}行)[/]")
                    return composite

                return None
        except Exception as e:
            console.log(f"[red]テロップの作成に失敗しました ({scene.id}): {e}[/]")
            import traceback
            console.log(f"[red]{traceback.format_exc()}[/]")
            return None

    def _resolve_xy(self, position: tuple, size: tuple[int, int]) -> tuple[float, float]:
        """("center", 100) のような配置指定を、画面上の左上座標(px)に変換する。"""
        screen = (self.script.video.width, self.script.video.height)
        result = []
        for value, length, full in zip(position, size, screen):
            if value == "center":
                result.append((full - length) / 2)
            elif value in ("left", "top"):
                result.append(0.0)
            elif value in ("right", "bottom"):
                result.append(float(full - length))
            else:
                result.append(float(value))
        return result[0], result[1]

    def _background_box(self, items: list[tuple], style: SubtitleStyle, default_color: str | None):
        """文字クリップ群 [(クリップ, 配置)] を囲む背景の矩形クリップを作る。背景色が無ければNone。

        文字が実際に描かれている範囲（マスク）から、background_padding だけ広げた大きさにする。
        半透明の色はマスクで表現する。
        """
        color = style.background or default_color
        if not color or not items:
            return None
        r, g, b, a = parse_color(color, style.background_opacity)
        if a == 0:
            return None
        pad = style.background_padding
        width, height = self.script.video.width, self.script.video.height

        left = top = float("inf")
        right = bottom = float("-inf")
        for clip, position in items:
            x, y = self._resolve_xy(position, clip.size)
            bx0, by0, bx1, by1 = _text_bbox(clip)
            left, top = min(left, x + bx0), min(top, y + by0)
            right, bottom = max(right, x + bx1), max(bottom, y + by1)

        # 余白を広げ、画面からはみ出す部分は切り詰める
        x0, y0 = max(0, math.floor(left - pad)), max(0, math.floor(top - pad))
        x1, y1 = min(width, math.ceil(right + pad)), min(height, math.ceil(bottom + pad))
        if x1 <= x0 or y1 <= y0:
            return None

        image = np.empty((y1 - y0, x1 - x0, 4), dtype=np.uint8)
        image[:, :] = (r, g, b, a)
        first = items[0][0]
        box = ImageClip(image, transparent=True).with_duration(first.duration).with_position((x0, y0))
        if first.start:
            box = box.with_start(first.start)
        return box

    def _resolve_font(self, font_path: Path | None) -> str | None:
        """フォントパスを解決する。見つからない場合はdefault_fontを使用。"""
        # フォントパスが指定されていて存在する場合
        if font_path and Path(font_path).exists():
            return str(font_path)

        # configのdefault_fontを試す
        if self.config and self.config.default_font:
            default_font = Path(self.config.default_font)
            if default_font.exists():
                console.log(f"[cyan]デフォルトフォントを使用: {default_font}[/]")
                return str(default_font)

        # どちらも見つからない場合はNone
        if font_path:
            console.log(f"[yellow]フォントが見つかりません: {font_path}, システムフォントを使用します[/]")
        return None

    def _apply_bgm(self, clip):
        video = self.script.video
        bgm_path = video.bgm
        if not bgm_path:
            return clip
        if not Path(bgm_path).exists():
            console.log(f"[yellow]BGMファイルが見つかりません: {bgm_path}[/]")
            return clip
        bgm_clip = self._open_media(lambda: AudioFileClip(str(bgm_path)), "video", "BGM", bgm_path)
        # BGMファイルの再生開始位置（--scene で途中から書き出すときはその分だけ進める）
        offset = video.bgm_start + self.start_offset
        end = offset + clip.duration
        if bgm_clip.duration < end and video.bgm_loop:
            # BGMが動画より短い場合は繰り返して動画の長さに合わせる
            console.log(
                f"[cyan]BGM ({bgm_clip.duration:.2f}秒) を動画の長さ ({clip.duration:.2f}秒) までループします[/]"
            )
            bgm_clip = bgm_clip.with_effects([AudioLoop(duration=end)])
        if offset >= bgm_clip.duration - 0.01:
            console.log(f"[yellow]BGMの再生開始位置 ({offset:.2f}秒) がBGMの長さを超えているため、BGMを付けません[/]")
            return clip
        if bgm_clip.duration < end:
            console.log(f"[yellow]BGMが動画より短いため、{bgm_clip.duration - offset:.2f}秒以降はBGMなしになります[/]")
        bgm_clip = bgm_clip.subclipped(offset, min(end, bgm_clip.duration))

        if video.bgm_volume != 1.0:
            bgm_clip = bgm_clip.with_volume_scaled(video.bgm_volume)
        effects = []
        if video.bgm_fade_in > 0:
            effects.append(AudioFadeIn(min(video.bgm_fade_in, bgm_clip.duration)))
        if video.bgm_fade_out > 0:
            effects.append(AudioFadeOut(min(video.bgm_fade_out, bgm_clip.duration)))
        if effects:
            bgm_clip = bgm_clip.with_effects(effects)

        if clip.audio:
            mixed = CompositeAudioClip([clip.audio, bgm_clip])
        else:
            mixed = bgm_clip
        clip = clip.with_audio(mixed)
        return clip


def _load_media(loader, scene_id: str, kind: str, path: Path):
    """素材ファイルを読み込み、壊れている・形式が違う場合は分かりやすいエラーにする。"""
    try:
        return loader()
    except VideoMakerError:
        raise
    except FileNotFoundError as exc:
        raise AssetError(f"{kind}ファイルが見つかりません ({scene_id}): {path}") from exc
    except Exception as exc:
        raise AssetError(
            f"{kind}ファイルを読み込めません ({scene_id}): {path}\n  {_first_line(exc)}",
            hint="ファイルが壊れていないか、対応している形式（画像: PNG/JPEG、動画: MP4、音声: WAV/MP3など）か確認してください。",
        ) from exc


def _first_line(exc: BaseException, limit: int = 300) -> str:
    """例外メッセージを短く要約する（FFmpegの長い出力を省略するため）。

    FFmpegのエラーは末尾の行に原因が出ることが多いので、先頭行と末尾行を残す。
    """
    text = str(exc).strip() or type(exc).__name__
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    summary = lines[0] if len(lines) == 1 else f"{lines[0]} ... {lines[-1]}"
    return summary if len(summary) <= limit else summary[:limit] + "…"


def _text_bbox(clip) -> tuple[int, int, int, int]:
    """文字クリップ内で、文字（縁取りを含む）が実際に描かれている範囲 (左, 上, 右, 下) を返す。

    TextClipは指定幅いっぱいの大きさになることがあるため、マスクから求める。
    """
    width, height = clip.size
    if clip.mask is None:
        return 0, 0, width, height
    alpha = np.asarray(clip.mask.get_frame(0))
    ys, xs = np.nonzero(alpha > 0.05)
    if len(xs) == 0:
        return 0, 0, width, height
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
