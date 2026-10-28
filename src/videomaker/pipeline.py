"""スクリプト解析から書き出しまでの高レベルパイプライン。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from rich.table import Table

from .config import AppConfig
from .errors import AssetError, VideoMakerError
from .models import SceneSpec, VideoScript
from .renderer import Renderer, RenderSettings
from .script_parser import parse_script
from .narration import split_narration, strip_pauses
from .timeline import resolve_durations
from .transitions import TRANSITION_NAMES, Transition
from .voicebox import VoiceboxClient
from .runlog import console


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
        if not any(scene.voiceover.strip() for scene in script.scenes):
            console.log("[cyan]ナレーションのあるシーンが無いため、Voiceboxの疎通確認をスキップします[/]")
            return
        client = self._voice_client()
        if not client.healthcheck():
            console.warn("Voiceboxヘルスチェックに失敗しました")
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
        # 音声なしモードやナレーションの無いシーンだけの場合はVoiceboxに接続しない（必要になったときに作る）
        client = None
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

        # シーンID → ナレーションに必要な長さ（前後の無音を含む）。シーンの長さを決めるのに使う
        narration: dict[str, float] = {}
        for scene in script.scenes:
            if not scene.voiceover.strip():
                continue
            if no_voice or (scene_ids and scene.id not in scene_ids):
                # 音声を作らないシーンは文字数から見積もる（書き出さないシーンは開始時刻の計算にだけ使う）
                if scene.duration is None:
                    narration[scene.id] = self._estimate_duration(scene, log=no_voice)
                continue
            if client is None:
                client = self._voice_client()
            # voice_overrideは指定した項目だけを上書きする（voiceを省略した場合はvideo.voiceを使う）
            override = scene.voice_override
            voice = (override.voice if override and override.voice else None) or script.video.voice
            speed = override.speed if override else None
            pitch = override.pitch if override else None

            # voiceoverを行ごとに分割（長い行は句読点を優先して自動分割。字幕と同じ分け方）
            # 各行はさらに、音声合成するテキストと {無音 秒数} の無音に分ける
            lines = split_narration(scene.voiceover, self.script.video.subtitle_line_chars(self.config.max_line_chars))
            line_interval = self.config.subtitle_line_interval if self.config else 0.0
            with_pause = any(line.has_pause for line in lines)

            if with_pause or (len(lines) > 1 and line_interval > 0):
                # 無音の指定があるか、複数行で行間間隔がある場合、テキストごとに合成して無音を挿入
                if len(lines) > 1:
                    console.log(f"[cyan]複数行音声を合成中: {scene.id} - {len(lines)}行、行間: {line_interval}秒[/]")
                else:
                    console.log(f"[cyan]無音を挟んで音声を合成中: {scene.id}[/]")

                # 各行の (テキストの音声ファイル または 無音の秒数) の並び
                line_items: list[list[Path | float]] = []
                for line in lines:
                    # テキストを音声合成（Voiceboxクライアント側でキャッシュされる）
                    line_items.append([
                        segment if isinstance(segment, float)
                        else client.synthesize(text=segment, voice=voice, speed=speed, pitch=pitch)
                        for segment in line.segments
                    ])

                # 各音声の長さから、字幕を表示するタイミングを求める
                lengths: dict[Path, float] = {}
                for item in (item for items in line_items for item in items):
                    if isinstance(item, Path) and item not in lengths:
                        audio = _open_audio(AudioFileClip, item, scene.id)
                        lengths[item] = audio.duration
                        audio.close()
                line_timings[scene.id] = _segment_timings(
                    [[("speech", lengths[item]) if isinstance(item, Path) else ("silence", item) for item in items]
                     for items in line_items],
                    margin_before,
                    line_interval,
                )

                # 結合済み音声は、音声ファイルと無音・行間から決まる名前でキャッシュする
                # （無音の指定が無い場合は以前と同じ名前になる）
                key_source = "|".join(
                    str(item) if isinstance(item, Path) else f"silence:{item:g}"
                    for items in line_items for item in items
                ) + f"|{line_interval}"
                key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()
                cache_dir = self.override_voice_cache or self.script.options.voice_cache_dir or Path(".cache/voice")
                cache_dir.mkdir(parents=True, exist_ok=True)
                combined_path = cache_dir / f"combined_{key}.wav"

                if combined_path.exists():
                    console.log(f"[green]結合済み音声のキャッシュを使用: {scene.id}[/]")
                else:
                    audio_clips = []
                    fps = None
                    # 無音は、先に音声を開いてそのサンプリングレートに合わせる
                    pending_silence: list[float] = []

                    def add_silence(seconds: float, label: str) -> None:
                        if seconds <= 0:
                            return
                        if AudioClip:
                            audio_clips.append(AudioClip(lambda t: 0, duration=seconds, fps=fps or 44100))
                            console.log(f"[cyan]  {label}に {seconds}秒の無音を追加[/]")
                        else:
                            console.warn(f"AudioClipが利用できないため、{label}の無音を追加できません")

                    for i, (line, items) in enumerate(zip(lines, line_items)):
                        for item in items:
                            if isinstance(item, float):
                                if fps is None:
                                    pending_silence.append(item)
                                else:
                                    add_silence(item, "ナレーションの途中")
                                continue
                            line_audio = _open_audio(AudioFileClip, item, scene.id)
                            if fps is None:
                                fps = line_audio.fps
                                for seconds in pending_silence:
                                    add_silence(seconds, "ナレーションの先頭")
                            audio_clips.append(line_audio)
                        console.log(f"[green]  行{i+1}の音声を合成: '{line.text}'[/]")

                        # 最後の行以外は行間の無音を追加
                        if i < len(lines) - 1:
                            add_silence(line_interval, "行間")

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
                    console.log(f"[green]音声を結合しました: {scene.id} (合計: {len(lines)}行)[/]")

                audio_map[scene.id] = combined_path
            else:
                # 単一行または行間間隔なしの場合は従来通り
                audio_map[scene.id] = client.synthesize(
                    text=scene.voiceover,
                    voice=voice,
                    speed=speed,
                    pitch=pitch,
                )

            # ナレーションに必要な長さ（音声の長さ + 前後の無音）
            audio_path = audio_map[scene.id]
            if audio_path.exists():
                audio_clip = _open_audio(AudioFileClip, audio_path, scene.id)
                base_duration = audio_clip.duration
                audio_clip.close()
                narration[scene.id] = base_duration + margin_before + margin_after
                if scene.duration is None and scene.start is None:
                    console.log(
                        f"[cyan]シーン {scene.id} のナレーション: {base_duration:.2f}秒"
                        f" + 無音 {margin_before:.2f}秒(前) + {margin_after:.2f}秒(後)"
                        f" = {narration[scene.id]:.2f}秒[/]"
                    )

        # 各シーンの長さを決める（start > duration > ナレーション > 動画素材 > BGMの終わり の順）
        starts = resolve_durations(
            script.scenes,
            narration,
            self._media_lengths(narration),
            self._bgm_remaining(),
            default_interval=script.video.scene_interval,
        )
        # --scene で途中から書き出すときは、最初のシーンの開始時刻からBGMを再生する
        start_offset = 0.0
        if scene_ids:
            for scene, start in zip(script.scenes, starts):
                if scene.id in scene_ids:
                    start_offset = start
                    break

        renderer = Renderer(
            script,
            config=self.config,
            settings=settings,
            no_voice=no_voice,
            line_timings=line_timings,
            start_offset=start_offset,
        )
        result = renderer.render(
            output_path=output_path,
            scene_ids=scene_ids,
            audio_map=audio_map,
        )
        if no_voice:
            self._print_timetable(renderer.timeline)
        return result

    def _estimate_duration(self, scene: SceneSpec, log: bool = True) -> float:
        """音声なしモードで、ナレーションの文字数からシーン長を見積もる。

        音声ありの場合と同じく、行間の間隔と前後の無音（voice_margin_*）、{無音 秒数} の無音も加える。
        """
        lines = split_narration(scene.voiceover, self.script.video.subtitle_line_chars(self.config.max_line_chars))
        if not lines:
            return 0.0
        # 空白は読み上げ時間に含めない
        chars = sum(len("".join(line.text.split())) for line in lines)
        speech = max(chars / self.config.no_voice_chars_per_second, self.config.no_voice_min_duration)
        interval = max(len(lines) - 1, 0) * self.config.subtitle_line_interval
        margin = self.config.voice_margin_before + self.config.voice_margin_after
        # {無音 秒数} で指定した無音
        pause = sum(line.pause_total for line in lines)
        duration = speech + interval + margin + pause
        if log:
            console.log(
                f"[cyan]シーン {scene.id} のdurationを文字数から見積もり: {chars}文字 -> {duration:.2f}秒[/]"
            )
        return duration

    def _media_lengths(self, narration: dict[str, float]) -> dict[str, float]:
        """長さの指定もナレーションも無い動画素材シーンについて、動画ファイルの長さを調べる。"""
        lengths: dict[str, float] = {}
        for scene in self.script.scenes:
            if scene.video is None or scene.duration is not None or scene.id in narration:
                continue
            if not Path(scene.video).exists():
                continue
            try:
                from moviepy import VideoFileClip
            except ImportError:
                from moviepy.editor import VideoFileClip
            try:
                clip = VideoFileClip(str(scene.video), audio=False)
            except Exception as exc:
                raise AssetError(f"動画ファイルを読み込めません ({scene.id}): {scene.video} ({exc})") from exc
            try:
                lengths[scene.id] = clip.duration
            finally:
                clip.close()
        return lengths

    def _bgm_remaining(self) -> float | None:
        """動画の先頭から見た、BGMの残りの長さ（BGMが無い場合はNone）。"""
        video = self.script.video
        if not video.bgm or not Path(video.bgm).exists():
            return None
        try:
            from moviepy import AudioFileClip
        except ImportError:
            from moviepy.editor import AudioFileClip
        clip = _open_audio(AudioFileClip, Path(video.bgm), "BGM")
        try:
            return clip.duration - video.bgm_start
        finally:
            clip.close()

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
            table.add_row(scene.id, _format_time(start), _format_time(end), switch, strip_pauses(scene.voiceover).strip())
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
    return _segment_timings([[("speech", duration)] for duration in durations], margin_before, interval)


def _segment_timings(
    lines: list[list[tuple[str, float]]], margin_before: float, interval: float
) -> list[tuple[float, float]]:
    """各行の (種類, 長さ) の並びから、各行が鳴る区間（シーン内の開始秒, 終了秒）を求める。

    種類は "speech"（音声）か "silence"（{無音 秒数} の無音）。行の区間は、その行の
    最初の音声の始まりから最後の音声の終わりまで（行の前後の無音は含めない）。
    結合音声は「前の無音 + 行1 + 行間 + 行2 + ...」の順に並ぶ。
    """
    timings = []
    current = margin_before
    for i, items in enumerate(lines):
        start = end = None
        for kind, duration in items:
            if kind == "speech":
                if start is None:
                    start = current
                end = current + duration
            current += duration
        if start is None:
            # 音声の無い行（通常は無い）は行の区間全体
            start, end = current, current
        timings.append((start, end))
        if i < len(lines) - 1:
            current += interval
    return timings
