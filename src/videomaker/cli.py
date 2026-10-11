"""VideoMaker CLIエントリポイント (Typer)。"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Callable, Optional, TypeVar

import click
import typer
from rich.console import Console
from rich.markup import escape

from .config import AppConfig, load_config
from .errors import VideoMakerError
from .models import Options
from .pipeline import VideoPipeline
from .renderer import RenderSettings
from .script_parser import parse_script
from .voicebox import clear_voice_cache

console = Console()
error_console = Console(stderr=True)

app = typer.Typer(help="テキストスクリプトから動画を生成するツール")

# --debug指定時はエラーのトレースバックを表示する
_debug = False

F = TypeVar("F", bound=Callable[..., None])


@app.callback()
def _main_options(
    debug: bool = typer.Option(False, "--debug", help="エラー発生時に詳細なトレースバックを表示する"),
) -> None:
    global _debug
    _debug = debug


def handle_errors(func: F) -> F:
    """コマンド実行中の例外を捕捉し、利用者向けのエラーメッセージを表示して終了する。"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (typer.Exit, typer.Abort, click.exceptions.ClickException):
            # typer/click自身の終了・確認キャンセル・引数エラーはそのまま任せる
            raise
        except VideoMakerError as exc:
            if _debug:
                error_console.print_exception()
            error_console.print(f"[bold red]エラー:[/] {escape(exc.message)}")
            if exc.hint:
                error_console.print(f"[yellow]ヒント:[/] {escape(exc.hint)}")
            raise typer.Exit(code=1) from exc
        except KeyboardInterrupt as exc:
            error_console.print("[yellow]処理を中断しました[/]")
            raise typer.Exit(code=130) from exc
        except Exception as exc:
            if _debug:
                error_console.print_exception()
            error_console.print(
                f"[bold red]予期しないエラーが発生しました:[/] {escape(type(exc).__name__)}: {escape(str(exc))}"
            )
            if not _debug:
                error_console.print("[yellow]ヒント:[/] --debug を付けて実行すると詳細が表示されます"
                                    "（例: videomaker --debug render story.yaml）")
            raise typer.Exit(code=1) from exc

    return wrapper  # type: ignore[return-value]


def _build_pipeline(
    script: Path,
    *,
    config_path: Optional[Path],
    voice_cache: Optional[Path],
    no_voice: bool = False,
) -> VideoPipeline:
    app_config: AppConfig = load_config(config_path)
    return VideoPipeline(
        script_path=script,
        config=app_config,
        override_voice_cache=voice_cache,
        no_voice=no_voice,
    )


def _build_settings(
    pipeline: VideoPipeline,
    *,
    preview: bool,
    encoder: Optional[str],
    fps: Optional[int],
    scale: Optional[float],
) -> RenderSettings:
    settings = RenderSettings.from_config(pipeline.config, preview=preview)
    if encoder:
        settings.encoder = encoder
    if fps:
        settings.fps = fps
    if scale:
        settings.scale = scale
    return settings


def _default_output(pipeline: VideoPipeline, script: Path, *, preview: bool) -> Path:
    """スクリプト指定のoutput_file、なければスクリプト名から出力パスを決める。"""
    if pipeline.script.video.output_file:
        output_path = Path(pipeline.script.video.output_file)
        console.log(f"[cyan]スクリプト指定の出力ファイル名を使用: {output_path}[/]")
    else:
        # スクリプトファイル名から生成（story.yaml -> story.mp4）
        output_path = Path("dist") / f"{script.stem}.mp4"
        console.log(f"[cyan]スクリプト名から出力ファイル名を生成: {output_path}[/]")
    if pipeline.no_voice:
        # 音声ありの書き出し結果を上書きしないよう別名にする
        output_path = output_path.with_name(f"{output_path.stem}_novoice{output_path.suffix}")
    if preview:
        output_path = output_path.with_name(f"{output_path.stem}_preview{output_path.suffix}")
    return output_path


NO_VOICE_HELP = "音声を合成せず、字幕・テロップのみの動画を作る（アフレコ用）"


@app.command(help="スクリプトと素材を検証します")
@handle_errors
def validate(
    script: Path = typer.Argument(..., exists=True, readable=True),
    config: Optional[Path] = typer.Option(None, "--config", help="設定ファイルパス"),
    voice_cache: Optional[Path] = typer.Option(
        None, "--voice-cache", help="音声キャッシュディレクトリ"
    ),
    no_voice: bool = typer.Option(False, "--no-voice", help=NO_VOICE_HELP),
) -> None:
    pipeline = _build_pipeline(script, config_path=config, voice_cache=voice_cache, no_voice=no_voice)
    pipeline.validate()
    console.print("[green]検証が完了しました[/]")


ENCODER_HELP = "映像エンコーダ (auto / cpu / nvenc / ffmpegのコーデック名)。未指定ならconfigのvideo_encoder"


@app.command(help="動画をレンダリングします")
@handle_errors
def render(
    script: Path = typer.Argument(..., exists=True, readable=True),
    output: Optional[Path] = typer.Option(None, "--out", help="出力先パス"),
    scene: Optional[list[str]] = typer.Option(None, "--scene", help="特定シーンのみレンダリング"),
    preview: bool = typer.Option(False, "--preview", "-p", help="低解像度・低fpsで高速にプレビュー出力"),
    encoder: Optional[str] = typer.Option(None, "--encoder", help=ENCODER_HELP),
    fps: Optional[int] = typer.Option(None, "--fps", min=1, help="出力フレームレートを上書き"),
    scale: Optional[float] = typer.Option(
        None, "--scale", min=0.1, max=1.0, help="出力解像度の倍率を上書き (例: 0.5)"
    ),
    config: Optional[Path] = typer.Option(None, "--config", help="設定ファイルパス"),
    voice_cache: Optional[Path] = typer.Option(
        None, "--voice-cache", help="音声キャッシュディレクトリ"
    ),
    no_voice: bool = typer.Option(False, "--no-voice", help=NO_VOICE_HELP),
) -> None:
    pipeline = _build_pipeline(script, config_path=config, voice_cache=voice_cache, no_voice=no_voice)
    pipeline.validate()
    output_path = output or _default_output(pipeline, script, preview=preview)
    settings = _build_settings(pipeline, preview=preview, encoder=encoder, fps=fps, scale=scale)
    pipeline.render(output_path=output_path, scene_ids=scene, settings=settings)
    console.print(f"[green]書き出し完了: {output_path}[/]")


@app.command(help="低解像度・低fpsのプレビュー動画を高速に作成します（render --preview と同じ）")
@handle_errors
def preview(
    script: Path = typer.Argument(..., exists=True, readable=True),
    scene: Optional[list[str]] = typer.Option(
        None, "--scene", "-s", help="プレビュー対象のシーンID（複数指定可、省略時は全シーン）"
    ),
    output: Optional[Path] = typer.Option(None, "--out", help="出力先パス"),
    encoder: Optional[str] = typer.Option(None, "--encoder", help=ENCODER_HELP),
    fps: Optional[int] = typer.Option(None, "--fps", min=1, help="フレームレート（既定: configのpreview_fps）"),
    scale: Optional[float] = typer.Option(
        None, "--scale", min=0.1, max=1.0, help="解像度の倍率（既定: configのpreview_scale）"
    ),
    config: Optional[Path] = typer.Option(None, "--config", help="設定ファイルパス"),
    voice_cache: Optional[Path] = typer.Option(
        None, "--voice-cache", help="音声キャッシュディレクトリ"
    ),
    no_voice: bool = typer.Option(False, "--no-voice", help=NO_VOICE_HELP),
) -> None:
    pipeline = _build_pipeline(script, config_path=config, voice_cache=voice_cache, no_voice=no_voice)
    pipeline.validate()
    output_path = output or _default_output(pipeline, script, preview=True)
    settings = _build_settings(pipeline, preview=True, encoder=encoder, fps=fps, scale=scale)
    pipeline.render(output_path=output_path, scene_ids=scene, settings=settings)
    console.print(f"[green]プレビュー完了: {output_path}[/]")


@app.command(help="音声キャッシュ(*.wav)をすべて削除します")
@handle_errors
def clear(
    script: Optional[Path] = typer.Argument(
        None, exists=True, readable=True, help="指定するとシナリオのvoice_cache_dirを対象にする"
    ),
    voice_cache: Optional[Path] = typer.Option(
        None, "--voice-cache", help="音声キャッシュディレクトリ（最優先）"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="確認せずに削除する"),
) -> None:
    # 優先順位: --voice-cache > シナリオのvoice_cache_dir > 既定(.cache/voice)
    if voice_cache:
        cache_dir = voice_cache
    elif script:
        cache_dir = parse_script(script).options.voice_cache_dir
    else:
        cache_dir = Options().voice_cache_dir

    files = [p for p in cache_dir.glob("*.wav") if p.is_file()] if cache_dir.is_dir() else []
    if not files:
        console.print(f"[yellow]削除する音声キャッシュはありません: {cache_dir}[/]")
        return
    if not yes:
        typer.confirm(f"{cache_dir} の音声キャッシュ {len(files)} 件を削除しますか?", abort=True)

    count, total = clear_voice_cache(cache_dir)
    console.print(
        f"[green]音声キャッシュを削除しました: {cache_dir} ({count} 件, {total / 1024 / 1024:.1f} MB)[/]"
    )


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
