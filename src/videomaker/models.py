"""YAMLスクリプトを表現するPydanticモデル群。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator, validator


# シーン切り替えのトランジション種別
# cut: 瞬間切り替え / fade: 黒を経由して切り替え / crossfade: 前のシーンに重ねて溶け込ませる
TransitionType = Literal["cut", "fade", "crossfade"]


def parse_time(value: float | int | str) -> float:
    """時刻・時間の指定を秒数に変換する。

    数値（秒）のほか、"分:秒"（例: "1:23.5"）や "時:分:秒"（例: "1:02:03"）の文字列に対応する。
    """
    if isinstance(value, bool):
        raise ValueError("時刻は秒数か \"分:秒\" 形式で指定してください")
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str):
        parts = value.strip().split(":")
        if len(parts) > 3 or not all(part.strip() for part in parts):
            raise ValueError(f"時刻の指定が不正です: {value!r}（例: 83.5、\"1:23.5\"、\"1:02:03\"）")
        try:
            numbers = [float(part) for part in parts]
        except ValueError as exc:
            raise ValueError(f"時刻の指定が不正です: {value!r}（例: 83.5、\"1:23.5\"、\"1:02:03\"）") from exc
        # 秒以外の桁（分・時）は整数、分と秒は60未満であること
        if any(n != int(n) for n in numbers[:-1]) or any(n >= 60 for n in numbers[1:]):
            raise ValueError(f"時刻の指定が不正です: {value!r}（例: 83.5、\"1:23.5\"、\"1:02:03\"）")
        seconds = 0.0
        for number in numbers:
            seconds = seconds * 60 + number
    else:
        raise ValueError("時刻は秒数か \"分:秒\" 形式で指定してください")
    if seconds < 0:
        raise ValueError("時刻に負の値は指定できません")
    return seconds


class SubtitleStyle(BaseModel):
    """字幕・テロップのスタイル定義。"""

    fill: str = Field("#FFFFFF", description="文字色 (hex)")
    stroke: str | None = Field("#000000", description="縁取り色")
    stroke_width: int | None = Field(None, ge=0, description="縁取り幅(px)")
    font_size: int | None = Field(None, ge=1, description="文字サイズ")
    padding: int = Field(24, ge=0, description="文字周囲のパディング(px)")
    background: str | None = Field(
        None, description="背景色。#RRGGBB、半透明は #RRGGBBAA（例: #00000080）や色名も可"
    )
    background_opacity: float | None = Field(
        None, ge=0.0, le=1.0, description="背景の不透明度（0.0=透明〜1.0=不透明）。背景色のアルファ値に掛け合わせる"
    )
    background_padding: int = Field(16, ge=0, description="文字の周りに広げる背景の余白(px)")

    @validator("background")
    def _check_background(cls, value: str | None) -> str | None:
        if value is not None:
            parse_color(value)
        return value


def parse_color(value: str, opacity: float | None = None) -> tuple[int, int, int, int]:
    """色の指定を (R, G, B, A) に変換する。A は 0〜255。

    #RGB / #RRGGBB / #RRGGBBAA / rgb(...) / 色名（red など）に対応し、
    opacity を指定するとアルファ値に掛け合わせる。
    """
    from PIL import ImageColor

    try:
        rgb = ImageColor.getrgb(value.strip())
    except (ValueError, AttributeError) as exc:
        raise ValueError(
            f"色の指定が不正です: {value!r}（例: \"#000000\"、半透明なら \"#00000080\"）"
        ) from exc
    r, g, b = rgb[:3]
    alpha = rgb[3] if len(rgb) == 4 else 255
    if opacity is not None:
        alpha = round(alpha * opacity)
    return r, g, b, alpha


class SubtitleConfig(BaseModel):
    """字幕出力の共通設定。"""

    font: Path | None = Field(
        None, description="字幕描画に利用するフォントパス"
    )
    position: Literal["top", "bottom"] = Field(
        "bottom", description="字幕の配置場所"
    )
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)

    @validator("font")
    def _resolve_font_path(cls, value: Optional[Path]) -> Optional[Path]:
        """フォントパスを解決する。見つからない場合はassets/fonts/も探す。"""
        if value is None:
            return value

        path = Path(value)
        # 既に存在する場合はそのまま返す
        if path.exists():
            return path

        # assets/fonts/を試す
        assets_path = Path("assets/fonts") / path.name
        if assets_path.exists():
            return assets_path

        # 見つからない場合は元のパスを返す（エラーは後で処理）
        return value


class TeletextConfig(BaseModel):
    """シーンごとのテロップ設定。"""

    text: str
    position: Literal[
        "top_left",
        "top_right",
        "bottom_left",
        "bottom_right",
        "center",
    ] = "top_left"
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    max_line_chars: Optional[int] = Field(
        None, ge=0, description="1行の最大文字数（video.teletext_max_line_chars より優先。0で分割しない）"
    )


class VoiceOverride(BaseModel):
    """Voiceboxに渡すシーン単位の上書き設定。"""

    voice: Optional[str] = None
    speed: Optional[float] = Field(
        None, description="読み上げ速度倍率"
    )
    pitch: Optional[float] = Field(
        None, description="ピッチ倍率"
    )
    volume: Optional[float] = Field(
        None, ge=0.0, le=2.0, description="音量倍率（1.0が100%）"
    )


class SceneSpec(BaseModel):
    """シーンの仕様。"""

    id: str
    image: Optional[Path] = None
    video: Optional[Path] = None
    start: Optional[float] = Field(
        None, description="シーンの開始時刻（動画の先頭からの秒数、または \"分:秒\"）。指定すると直前のシーンの長さをこの時刻に合わせる"
    )
    duration: Optional[float] = Field(None, gt=0, description="シーン長 (秒)。未指定の場合はナレーション音声の長さを使用")
    voiceover: str = Field("", description="ナレーション。省略または空ならナレーションなしのシーン")
    subtitle: Optional[str] = None
    teletext: Optional[TeletextConfig] = None
    transition: Optional[TransitionType] = Field(
        None, description="前のシーンからこのシーンへ切り替わるときのトランジション。未指定ならvideo.transition"
    )
    transition_duration: Optional[float] = Field(
        None, gt=0, description="トランジションの長さ（秒）。未指定ならvideo.transition_duration"
    )
    kenburns: bool = False
    voice_override: Optional[VoiceOverride] = None

    @field_validator("start", mode="before")
    @classmethod
    def _parse_start(cls, value):
        return None if value is None else parse_time(value)

    @field_validator("voiceover", mode="before")
    @classmethod
    def _voiceover_none_to_empty(cls, value):
        # YAMLで「voiceover:」とだけ書いた場合（None）も空として扱う
        return "" if value is None else value

    @validator("id")
    def _id_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("id は空白不可です")
        return value

    @validator("image")
    def _resolve_image_path(cls, value: Optional[Path]) -> Optional[Path]:
        """画像パスを解決する。見つからない場合はassets/images/も探す。"""
        if value is None:
            return value

        path = Path(value)
        # 既に存在する場合はそのまま返す
        if path.exists():
            return path

        # assets/images/を試す
        assets_path = Path("assets/images") / path.name
        if assets_path.exists():
            return assets_path

        # 見つからない場合は元のパスを返す（エラーは後で処理）
        return value

    @validator("video")
    def _resolve_video_path(cls, value: Optional[Path]) -> Optional[Path]:
        """ビデオパスを解決する。見つからない場合はassets/videos/も探す。"""
        if value is None:
            return value

        path = Path(value)
        # 既に存在する場合はそのまま返す
        if path.exists():
            return path

        # assets/videos/を試す
        assets_path = Path("assets/videos") / path.name
        if assets_path.exists():
            return assets_path

        # 見つからない場合は元のパスを返す（エラーは後で処理）
        return value

    @model_validator(mode="after")
    def _check_source(self) -> "SceneSpec":
        if self.image is None and self.video is None:
            raise ValueError("image または video のいずれかが必要です")
        if self.image is not None and self.video is not None:
            raise ValueError("image と video は同時に指定できません")
        return self


class VideoSpec(BaseModel):
    """動画全体の仕様。"""

    width: int = Field(1920, gt=0)
    height: int = Field(1080, gt=0)
    fps: int = Field(30, gt=0)
    bgm: Optional[Path] = None
    voice: Optional[str] = Field(
        None, description="Voiceboxのプリセット名"
    )
    subtitle: SubtitleConfig = Field(default_factory=SubtitleConfig)
    max_line_chars: Optional[int] = Field(
        None,
        ge=0,
        description="ナレーション・字幕の1行の最大文字数（config の max_line_chars より優先。0で分割しない）",
    )
    teletext_max_line_chars: Optional[int] = Field(
        None, ge=0, description="テロップの1行の最大文字数。超える行は自動で折り返す（未指定・0で折り返さない）"
    )
    transition: TransitionType = Field("cut", description="シーン切り替えのトランジション（全シーン共通の既定値）")
    transition_duration: float = Field(0.5, gt=0, description="トランジションの長さ（秒）の既定値")
    output_file: Optional[Path] = Field(
        None, description="出力ファイル名（省略時はスクリプト名から自動生成）"
    )
    bgm_volume: float = Field(0.4, ge=0.0, le=2.0, description="BGMの音量（1.0が100%）")
    bgm_start: float = Field(0.0, description="BGMファイルのどの位置から再生するか（秒、または \"分:秒\"）")
    bgm_fade_in: float = Field(0.0, ge=0.0, description="BGMのフェードインの長さ（秒）")
    bgm_fade_out: float = Field(0.0, ge=0.0, description="BGMのフェードアウトの長さ（秒）")
    bgm_loop: bool = Field(True, description="BGMが動画より短い場合に繰り返すか")

    def subtitle_line_chars(self, default: int) -> int:
        """ナレーション・字幕の1行の最大文字数を返す（シナリオの指定 > config の既定値）。"""
        return self.max_line_chars if self.max_line_chars is not None else default

    @field_validator("bgm_start", mode="before")
    @classmethod
    def _parse_bgm_start(cls, value):
        return parse_time(value)

    @validator("bgm")
    def _resolve_bgm_path(cls, value: Optional[Path]) -> Optional[Path]:
        """BGMパスを解決する。見つからない場合はassets/sounds/も探す。"""
        if value is None:
            return value

        path = Path(value)
        # 既に存在する場合はそのまま返す
        if path.exists():
            return path

        # assets/sounds/を試す
        assets_path = Path("assets/sounds") / path.name
        if assets_path.exists():
            return assets_path

        # 見つからない場合は元のパスを返す（エラーは後で処理）
        return value


class Options(BaseModel):
    """CLIオプションからも上書きされる実行時設定。"""

    voice_cache_dir: Path = Path(".cache/voice")
    no_voice: bool = Field(
        False, description="trueで音声合成を行わず、字幕・テロップのみの動画を作る（アフレコ用）"
    )
    subtitle_format: Literal["burn", "srt"] = "burn"
    keep_temp: bool = False
    workers: int = Field(1, ge=1, le=8)


class VideoScript(BaseModel):
    """スクリプト全体。"""

    video: VideoSpec
    scenes: list[SceneSpec]
    options: Options = Field(default_factory=Options)

    @model_validator(mode="after")
    def _unique_scene_ids(self) -> "VideoScript":
        seen = set()
        for scene in self.scenes:
            if scene.id in seen:
                raise ValueError(f"scene id が重複しています: {scene.id}")
            seen.add(scene.id)
        if not self.scenes:
            raise ValueError("少なくとも1つのシーンが必要です")
        first = self.scenes[0]
        if first.start is not None and first.start > 0:
            raise ValueError(
                f"最初のシーン {first.id} の start は 0 にしてください（曲の途中から始める場合は video.bgm_start を使います）"
            )
        # start は後のシーンほど大きくなければならない
        previous = None
        for scene in self.scenes:
            if scene.start is None:
                continue
            if previous is not None and scene.start <= previous.start:
                raise ValueError(
                    f"シーン {scene.id} の start ({scene.start:g}秒) が、"
                    f"前のシーン {previous.id} の start ({previous.start:g}秒) 以前になっています"
                )
            previous = scene
        return self
