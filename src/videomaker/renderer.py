"""MoviePyベースの簡易レンダラー。"""

from __future__ import annotations

import bisect
import functools
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
    from moviepy.audio.fx import AudioLoop
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
from .models import SceneSpec, VideoScript
from .textsplit import split_text_lines
from .transitions import SpeechSpan, Transition, compose_timeline, plan_transitions

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
    ) -> None:
        self.script = script
        self.config = config
        self.settings = settings or RenderSettings.from_config(config)
        # 音声なしモード（アフレコ用）では音声が無いことを警告しない
        self.no_voice = no_voice
        # シーンごとの各行の音声が鳴る区間。あれば字幕をナレーションに合わせて表示する
        self.line_timings = line_timings or {}
        # 書き出したシーンの (シーン, 開始秒, 終了秒, そのシーンへの切り替え)。アフレコ用タイムテーブルに使う
        self.timeline: list[tuple[SceneSpec, float, float, Transition]] = []

    def render(
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
        clips: list[VideoClip] = []
        for i, scene in enumerate(scenes):
            # クロスフェードで前後のシーンと重なる区間は字幕を出さない
            next_overlap = plans[i + 1].overlap if i + 1 < len(scenes) else 0.0
            clip = self._build_scene_clip(
                scene, audio_map, subtitle_window=(plans[i].overlap, scene.duration - next_overlap)
            )
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
            clip = _load_media(lambda: VideoFileClip(str(scene.video)), scene.id, "動画", scene.video)
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
            voice = _load_media(lambda: AudioFileClip(str(audio_path)), scene.id, "音声", audio_path)

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
        elif not self.no_voice:
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
                return txt_clip
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

            if len(lines) == 1:
                # 単一行の場合は従来通り
                padding = 50
                position_map = {
                    "top_left": (padding, padding),
                    "top_right": (self.script.video.width - padding, padding),
                    "bottom_left": (padding, self.script.video.height - padding),
                    "bottom_right": (self.script.video.width - padding, self.script.video.height - padding),
                    "center": ("center", "center"),
                }
                position = position_map.get(teletext.position, ("center", "center"))

                console.log(f"[cyan]テロップを作成中: {scene.id} - テキスト='{teletext.text}', 位置={position}, font_size={font_size}[/]")

                txt_clip = TextClip(
                    text=teletext.text,
                    font=font,
                    font_size=font_size,
                    color=color,
                    stroke_color=stroke_color if stroke_color else None,
                    stroke_width=stroke_width if stroke_color else 0,
                    duration=scene.duration,
                ).with_position(position)

                console.log(f"[green]テロップを作成しました: {scene.id}[/]")
                return txt_clip
            else:
                # 複数行の場合は行ごとに分けて表示
                console.log(f"[cyan]複数行テロップを作成中: {scene.id} - {len(lines)}行[/]")

                clips = []
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

                    if "left" in base_position:
                        x_pos = padding
                    elif "right" in base_position:
                        x_pos = self.script.video.width - padding
                    else:  # center
                        x_pos = "center"

                    txt_clip = TextClip(
                        text=line,
                        font=font,
                        font_size=font_size,
                        color=color,
                        stroke_color=stroke_color if stroke_color else None,
                        stroke_width=stroke_width if stroke_color else 0,
                        duration=scene.duration,
                    ).with_position((x_pos, y_pos))

                    clips.append(txt_clip)
                    console.log(f"[green]  行{i+1}: '{line}' at ({x_pos}, {y_pos})[/]")

                # 複数のテキストクリップを結合
                if clips:
                    composite = CompositeVideoClip(clips, size=(self.script.video.width, self.script.video.height))
                    console.log(f"[green]複数行テロップを作成しました: {scene.id} ({len(lines)}行)[/]")
                    return composite

                return None
        except Exception as e:
            console.log(f"[red]テロップの作成に失敗しました ({scene.id}): {e}[/]")
            import traceback
            console.log(f"[red]{traceback.format_exc()}[/]")
            return None

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
        bgm_path = self.script.video.bgm
        if not bgm_path:
            return clip
        if not Path(bgm_path).exists():
            console.log(f"[yellow]BGMファイルが見つかりません: {bgm_path}[/]")
            return clip
        bgm_clip = _load_media(
            lambda: AudioFileClip(str(bgm_path)).with_volume_scaled(0.4), "video", "BGM", bgm_path
        )
        if bgm_clip.duration < clip.duration:
            # BGMが動画より短い場合は繰り返して動画の長さに合わせる
            console.log(
                f"[cyan]BGM ({bgm_clip.duration:.2f}秒) を動画の長さ ({clip.duration:.2f}秒) までループします[/]"
            )
            bgm_clip = bgm_clip.with_effects([AudioLoop(duration=clip.duration)])
        else:
            bgm_clip = bgm_clip.subclipped(0, clip.duration)

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
