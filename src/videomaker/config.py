"""CLI全体で共有する設定ローダ。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from .errors import ConfigError, format_validation_error, load_yaml_mapping


class AppConfig(BaseModel):
    """VoiceboxやFFmpegの接続情報を持つ。"""

    voicebox_url: str = Field("http://127.0.0.1:9000/api/tts")
    voicebox_health_url: str | None = None
    voicebox_mode: Literal["generic", "voicevox"] = Field("generic")
    voicebox_token: str | None = None
    voicebox_voice_map: dict[str, str] = Field(default_factory=dict)
    voicebox_timeout: float = Field(30.0, gt=0, description="Voicebox API呼び出しのタイムアウト（秒）")
    voicebox_reading_map: dict[str, str] = Field(
        default_factory=dict,
        description="音声合成前に置き換える読み（例: {'方': 'かた'}）。字幕には影響しない",
    )
    ffmpeg_path: Path | None = None
    default_font: Path | None = Field(None, description="デフォルトフォントファイルパス")
    image_dir: Path | None = Field(None, description="デフォルト画像ディレクトリ")

    # 字幕のデフォルト設定
    subtitle_font_size: int = Field(48, ge=1, description="字幕の文字サイズ")
    subtitle_color: str = Field("#FFFFFF", description="字幕の文字色")
    subtitle_stroke_color: str = Field("#000000", description="字幕の縁取り色")
    subtitle_stroke_width: int = Field(2, ge=0, description="字幕の縁取り幅")
    subtitle_line_interval: float = Field(0.0, ge=0.0, description="複数行字幕の行間時間（秒）")
    max_line_chars: int = Field(
        30,
        ge=0,
        description="ナレーション・字幕の1行の最大文字数の目安。超える行は句読点を優先して自動分割する（0で分割しない）",
    )

    # テロップのデフォルト設定
    teletext_font_size: int = Field(60, ge=1, description="テロップの文字サイズ")
    teletext_color: str = Field("#FFE066", description="テロップの文字色")
    teletext_stroke_color: str = Field("#222222", description="テロップの縁取り色")
    teletext_stroke_width: int = Field(3, ge=0, description="テロップの縁取り幅")

    # 音声のデフォルト設定
    voice_volume: float = Field(1.0, ge=0.0, le=2.0, description="ナレーション音量（1.0が100%）")
    voice_margin_before: float = Field(0.0, ge=0.0, description="音声の前に追加する無音時間（秒）")
    voice_margin_after: float = Field(0.0, ge=0.0, description="音声の後に追加する無音時間（秒）")

    # 音声なしモード（アフレコ用）の設定
    no_voice_chars_per_second: float = Field(
        6.0, gt=0.0, description="音声なしモードでdurationを見積もる読み上げ速度（1秒あたりの文字数）"
    )
    no_voice_min_duration: float = Field(
        2.0, gt=0.0, description="音声なしモードで見積もるシーン長の最小値（秒）"
    )

    # エンコード設定
    video_encoder: str = Field(
        "auto",
        description="映像エンコーダ。auto（NVENCが使えればGPU）/ cpu（libx264）/ nvenc（h264_nvenc）/ ffmpegのコーデック名",
    )
    video_preset: str | None = Field(None, description="エンコーダのプリセット。未指定ならエンコーダごとの既定値")
    video_quality: int | None = Field(
        None, ge=0, le=51, description="画質（libx264はCRF、NVENCはCQ）。小さいほど高画質。未指定なら既定値"
    )

    # プレビューモードの設定
    preview_scale: float = Field(0.5, gt=0.0, le=1.0, description="プレビュー時の解像度倍率")
    preview_fps: int = Field(10, gt=0, description="プレビュー時のフレームレート")


def load_config(path: Path | None) -> AppConfig:
    """指定パスまたはデフォルト(`config.yaml`)から設定を読み込む。"""
    if path is None:
        default_path = Path("config.yaml")
        if not default_path.exists():
            return AppConfig()
        path = default_path

    data = load_yaml_mapping(path, ConfigError, "設定ファイル")
    try:
        return AppConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(
            f"設定ファイルの内容が不正です: {path}\n{format_validation_error(exc)}",
            hint="config.example.yaml を参考に設定値を確認してください。",
        ) from exc
