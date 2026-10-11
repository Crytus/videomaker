"""スクリプト解析から書き出しまでの高レベルパイプライン。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from rich.console import Console
from rich.table import Table

from .config import AppConfig
from .errors import AssetError, VideoMakerError
from .models import SceneSpec, VideoScript
from .renderer import Renderer, RenderSettings
from .script_parser import parse_script
from .textsplit import split_text_lines
from .transitions import TRANSITION_NAMES, Transition
from .voicebox import VoiceboxClient

console = Console()


class VideoPipeline:
    """CLIから利用される高水準API。"""

    def __init__(
        self,
        script_path: Path,
        *,
        config: AppConfig,
        override_voice_cache: Path | None = None,
        no_voice: bool = False,
    ) -> None:
        self.script_path = script_path
        self.config = config
        self.override_voice_cache = override_voice_cache
        self._no_voice = no_voice
        self._script: VideoScript | None = None

    @property
    def no_voice(self) -> bool:
        """音声なしモードか（CLIの--no-voice または スクリプトのoptions.no_voice）。"""
        return self._no_voice or self.script.options.no_voice

    @property
    def script(self) -> VideoScript:
        if self._script is None:
            self._script = parse_script(self.script_path)
        return self._script

    def validate(self) -> None:
        """素材ファイルやVoicebox疎通を確認する。"""
        script = self.script
        missing = []

        # 画像ファイルの検証と自動検索
        # メディアファイルの検証と自動検索
        for scene in script.scenes:
            if scene.image:
                resolved_image = self._resolve_image_path(scene.image)
                if resolved_image:
                    # 解決されたパスに更新
                    scene.image = resolved_image
                    console.log(f"[green]画像ファイルを検出: {scene.id} -> {resolved_image}[/]")
                else:
                    missing.append(("scene", scene.id, scene.image))
            elif scene.video:
                if not scene.video.exists():
                     missing.append(("scene (video)", scene.id, scene.video))

        if script.video.bgm and not Path(script.video.bgm).exists():
            missing.append(("bgm", "video", script.video.bgm))
        font = script.video.subtitle.font
        if font and not Path(font).exists():
            missing.append(("font", "subtitle", font))

        if missing:
            detail = "\n".join(f"- {kind}: {label} -> {path}" for kind, label, path in missing)
            raise AssetError(
                f"素材ファイルが見つかりません:\n{detail}",
                hint="スクリプトのパス指定（スクリプトファイルからの相対パス）や、config.yamlのimage_dirを確認してください。",
            )

        if self.no_voice:
            console.log("[cyan]音声なしモードのため、Voiceboxの疎通確認をスキップします[/]")
            return
        client = self._voice_client()
        if not client.healthcheck():
            console.log("[yellow]Voiceboxヘルスチェックに失敗しました[/]")
        else:
            console.log("[green]Voiceboxと疎通できました[/]")

    def render(
        self,
        *,
        output_path: Path,
        scene_ids: Iterable[str] | None = None,
        settings: RenderSettings | None = None,
    ) -> Path:
        """レンダリングを実行する。"""
        script = self.script
        no_voice = self.no_voice
        # 音声なしモードではVoiceboxに接続しない
        client = None if no_voice else self._voice_client()
        audio_map: dict[str, Path] = {}
        # 1行ずつ合成したシーンの、各行の音声が鳴る区間（シーン内の開始秒, 終了秒）。字幕を音声に合わせるのに使う
        line_timings: dict[str, list[tuple[float, float]]] = {}
        margin_before = self.config.voice_margin_before if self.config else 0.0
        margin_after = self.config.voice_margin_after if self.config else 0.0
        if no_voice:
            console.log("[cyan]音声なしモード: 音声合成を行わず、字幕・テロップのみで作成します[/]")

        # AudioClipのインポート
        try:
            from moviepy import AudioClip, AudioFileClip, concatenate_audioclips
        except ImportError:
            try:
                from moviepy.editor import AudioFileClip, concatenate_audioclips
                from moviepy.audio.AudioClip import AudioClip
            except:
                from moviepy.editor import AudioFileClip, concatenate_audioclips
                AudioClip = None

        for scene in script.scenes:
            if scene_ids and scene.id not in scene_ids:
                continue
            if no_voice:
                if scene.duration is None:
                    scene.duration = self._estimate_duration(scene)
                continue
            voice =scene.voice_override.voice if scene.voice_override else script.video.voice
            speed = scene.voice_override.speed if scene.voice_override else None
            pitch = scene.voice_override.pitch if scene.voice_override else None

            # voiceoverを行ごとに分割（長い行は句読点を優先して自動分割。字幕と同じ分け方）
            lines = split_text_lines(scene.voiceover, self.config.max_line_chars)
            line_interval = self.config.subtitle_line_interval if self.config else 0.0

            if len(lines) > 1 and line_interval > 0:
                # 複数行で行間間隔がある場合、各行を別々に合成して無音を挿入
                console.log(f"[cyan]複数行音声を合成中: {scene.id} - {len(lines)}行、行間: {line_interval}秒[/]")

                line_paths = []
                for i, line in enumerate(lines):
                    # 各行を音声合成（Voiceboxクライアント側でキャッシュされる）
                    line_paths.append(
                        client.synthesize(text=line, voice=voice, speed=speed, pitch=pitch)
                    )

                # 各行の音声の長さから、字幕を表示するタイミングを求める
                line_durations = []
                for line_audio_path in line_paths:
                    line_audio = _open_audio(AudioFileClip, line_audio_path, scene.id)
                    line_durations.append(line_audio.duration)
                    line_audio.close()
                line_timings[scene.id] = _line_timings(line_durations, margin_before, line_interval)

                # 結合済み音声は、行ごとの音声ファイルと行間から決まる名前でキャッシュする
                key_source = "|".join(str(path) for path in line_paths) + f"|{line_interval}"
                key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()
                cache_dir = self.override_voice_cache or self.script.options.voice_cache_dir or Path(".cache/voice")
                cache_dir.mkdir(parents=True, exist_ok=True)
                combined_path = cache_dir / f"combined_{key}.wav"

                if combined_path.exists():
                    console.log(f"[green]結合済み音声のキャッシュを使用: {scene.id}[/]")
                else:
                    audio_clips = []
                    for i, (line, line_audio_path) in enumerate(zip(lines, line_paths)):
                        line_audio = _open_audio(AudioFileClip, line_audio_path, scene.id)
                        audio_clips.append(line_audio)
                        console.log(f"[green]  行{i+1}の音声を合成: '{line}' ({line_audio.duration:.2f}秒)[/]")

                        # 最後の行以外は行間の無音を追加
                        if i < len(lines) - 1:
                            if AudioClip:
                                silence = AudioClip(lambda t: 0, duration=line_interval, fps=line_audio.fps or 44100)
                                audio_clips.append(silence)
                                console.log(f"[cyan]  行間に {line_interval}秒の無音を追加[/]")
                            else:
                                console.log(f"[yellow]AudioClipが利用できないため、行間の無音を追加できません[/]")

                    # 音声を連結（書き込み途中のファイルをキャッシュとして残さないよう一時名で書いてから置き換える）
                    combined_audio = concatenate_audioclips(audio_clips)
                    temp_path = combined_path.with_suffix(".tmp.wav")
                    try:
                        combined_audio.write_audiofile(str(temp_path), codec="pcm_s16le", logger=None)
                        temp_path.replace(combined_path)
                    except Exception as exc:
                        raise AssetError(
                            f"複数行音声の結合ファイルを書き出せません: {combined_path} ({exc})"
                        ) from exc

                    # クリーンアップ
                    for clip in audio_clips:
                        try:
                            clip.close()
                        except:
                            pass
                    combined_audio.close()
                    console.log(f"[green]複数行音声を結合しました: {scene.id} (合計: {len(lines)}行)[/]")

                audio_map[scene.id] = combined_path
            else:
                # 単一行または行間間隔なしの場合は従来通り
                audio_map[scene.id] = client.synthesize(
                    text=scene.voiceover,
                    voice=voice,
                    speed=speed,
                    pitch=pitch,
                )

            # durationが未指定の場合は音声ファイルの長さを使い、
            # 指定されていてもナレーションより短い場合は、途中で切れないよう延長する
            audio_path = audio_map[scene.id]
            if audio_path.exists():
                audio_clip = _open_audio(AudioFileClip, audio_path, scene.id)
                base_duration = audio_clip.duration
                audio_clip.close()

                # 無音の時間を追加
                needed = base_duration + margin_before + margin_after
                if scene.duration is None:
                    scene.duration = needed
                    if margin_before > 0 or margin_after > 0:
                        console.log(f"[cyan]シーン {scene.id} のdurationを音声長から設定: {base_duration:.2f}秒 + 無音 {margin_before:.2f}秒(前) + {margin_after:.2f}秒(後) = {scene.duration:.2f}秒[/]")
                    else:
                        console.log(f"[cyan]シーン {scene.id} のdurationを音声長から設定: {scene.duration:.2f}秒[/]")
                elif scene.duration < needed - 0.01:
                    console.log(
                        f"[yellow]シーン {scene.id} のduration ({scene.duration:.2f}秒) がナレーション"
                        f"（前後の無音を含めて {needed:.2f}秒）より短いため、{needed:.2f}秒に延長しました[/]"
                    )
                    scene.duration = needed

        renderer = Renderer(
            script, config=self.config, settings=settings, no_voice=no_voice, line_timings=line_timings
        )
        result = renderer.render(
            output_path=output_path,
            scene_ids=scene_ids,
            audio_map=audio_map,
        )
        if no_voice:
            self._print_timetable(renderer.timeline)
        return result

    def _estimate_duration(self, scene: SceneSpec) -> float:
        """音声なしモードで、ナレーションの文字数からシーン長を見積もる。

        音声ありの場合と同じく、行間の間隔と前後の無音（voice_margin_*）も加える。
        """
        lines = split_text_lines(scene.voiceover, self.config.max_line_chars)
        # 空白は読み上げ時間に含めない
        chars = sum(len("".join(line.split())) for line in lines)
        speech = max(chars / self.config.no_voice_chars_per_second, self.config.no_voice_min_duration)
        interval = max(len(lines) - 1, 0) * self.config.subtitle_line_interval
        margin = self.config.voice_margin_before + self.config.voice_margin_after
        duration = speech + interval + margin
        console.log(
            f"[cyan]シーン {scene.id} のdurationを文字数から見積もり: {chars}文字 -> {duration:.2f}秒[/]"
        )
        return duration

    def _print_timetable(self, timeline: list[tuple[SceneSpec, float, float, Transition]]) -> None:
        """アフレコ用に、各シーンの開始・終了時刻とナレーションを一覧表示する。

        クロスフェードで前後のシーンが重なる場合は、重なった時刻のまま表示する。
        """
        table = Table(title="アフレコ用タイムテーブル")
        table.add_column("シーン")
        table.add_column("開始", justify="right")
        table.add_column("終了", justify="right")
        table.add_column("切り替え")
        table.add_column("ナレーション")
        for scene, start, end, transition in timeline:
            if transition.kind == "cut":
                switch = ""
            else:
                switch = f"{TRANSITION_NAMES[transition.kind]} {transition.duration:.2f}秒"
            table.add_row(scene.id, _format_time(start), _format_time(end), switch, scene.voiceover.strip())
        console.print(table)

    def _resolve_image_path(self, image_path: Path) -> Path | None:
        """画像ファイルのパスを解決する。存在しない場合はimage_dirから検索。"""
        # パスが既に存在する場合
        if image_path.exists():
            return image_path

        # image_dirが設定されている場合、そこから検索
        if self.config.image_dir:
            image_dir = Path(self.config.image_dir)
            if image_dir.exists() and image_dir.is_dir():
                # ファイル名のみを取得して、image_dirから検索
                filename = image_path.name
                candidate = image_dir / filename
                if candidate.exists():
                    console.log(f"[cyan]画像をデフォルトディレクトリから検出: {candidate}[/]")
                    return candidate

        # 見つからない場合
        return None

    def _voice_client(self) -> VoiceboxClient:
        voice_cache = (
            self.override_voice_cache
            if self.override_voice_cache
            else self.script.options.voice_cache_dir
        )
        return VoiceboxClient(
            base_url=self.config.voicebox_url,
            health_url=self.config.voicebox_health_url,
            mode=self.config.voicebox_mode,
            token=self.config.voicebox_token,
            voice_map=self.config.voicebox_voice_map,
            reading_map=self.config.voicebox_reading_map,
            timeout=self.config.voicebox_timeout,
            cache_dir=voice_cache,
        )


def _open_audio(audio_file_clip, path: Path, scene_id: str):
    """音声ファイルを開き、壊れている場合などは分かりやすいエラーにする。"""
    try:
        return audio_file_clip(str(path))
    except VideoMakerError:
        raise
    except Exception as exc:
        raise AssetError(
            f"シーン {scene_id} の音声ファイルを読み込めません: {path} ({exc})",
            hint="音声キャッシュが壊れている可能性があります。`videomaker clear` でキャッシュを削除して再実行してください。",
        ) from exc


def _format_time(seconds: float) -> str:
    """秒数を「分:秒.小数」の表記にする（例: 75.5 -> 1:15.50）。"""
    minutes, sec = divmod(seconds, 60)
    return f"{int(minutes)}:{sec:05.2f}"


def _line_timings(
    durations: list[float], margin_before: float, interval: float
) -> list[tuple[float, float]]:
    """1行ずつ合成した音声の長さから、各行が鳴る区間（シーン内の開始秒, 終了秒）を求める。

    結合音声は「前の無音 + 行1 + 行間 + 行2 + ...」の順に並ぶ。
    """
    timings = []
    current = margin_before
    for duration in durations:
        timings.append((current, current + duration))
        current += duration + interval
    return timings
