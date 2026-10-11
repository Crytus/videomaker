"""VideoMaker共通の例外クラスと、エラーメッセージ整形ヘルパー。

CLIはVideoMakerErrorを捕捉して、トレースバックではなく
利用者向けのメッセージを表示する。
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError


class VideoMakerError(Exception):
    """利用者に表示すべきエラーの基底クラス。"""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return self.message


class ConfigError(VideoMakerError):
    """設定ファイル(config.yaml)の不足・形式エラー。"""


class ScriptError(VideoMakerError):
    """スクリプトYAMLの不足・形式エラー。"""


class AssetError(VideoMakerError):
    """画像・動画・音声・フォントなど素材ファイルの不足・読み込みエラー。"""


class RenderError(VideoMakerError):
    """動画の合成・書き出し時のエラー。"""


# pydanticのエラー種別ごとの日本語メッセージ（未登録の種別は元のメッセージを使う）
_VALIDATION_MESSAGES = {
    "missing": "必須項目がありません",
    "extra_forbidden": "未知の項目です",
    "string_type": "文字列を指定してください",
    "int_type": "整数を指定してください",
    "int_parsing": "整数を指定してください",
    "int_from_float": "整数を指定してください",
    "float_type": "数値を指定してください",
    "float_parsing": "数値を指定してください",
    "bool_type": "true / false を指定してください",
    "bool_parsing": "true / false を指定してください",
    "dict_type": "マップ（キー: 値）形式で指定してください",
    "model_type": "マップ（キー: 値）形式で指定してください",
    "list_type": "リスト（- 項目）形式で指定してください",
    "path_type": "パスを文字列で指定してください",
}


def format_validation_error(exc: ValidationError) -> str:
    """pydanticの検証エラーを「場所: 内容」の箇条書きに整形する。"""
    lines = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ())) or "(トップレベル)"
        err_type = err.get("type", "")
        if err_type in _VALIDATION_MESSAGES:
            message = _VALIDATION_MESSAGES[err_type]
        else:
            message = str(err.get("msg", ""))
            # カスタムバリデータのValueErrorは "Value error, " が前置されるので取り除く
            message = message.removeprefix("Value error, ")
        if err_type == "literal_error" and "expected" in err.get("ctx", {}):
            message = f"指定できる値は {err['ctx']['expected']} です"
        if "input" in err and err_type not in ("missing",) and not isinstance(
            err["input"], (dict, list)
        ):
            message += f"（指定値: {err['input']!r}）"
        lines.append(f"- {loc}: {message}")
    return "\n".join(lines)


def format_yaml_error(exc: yaml.YAMLError) -> str:
    """YAML構文エラーを行・列番号付きで整形する。"""
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None) or str(exc)
    if mark is not None:
        return f"{mark.line + 1}行目 {mark.column + 1}列目付近: {problem}"
    return problem


def read_text_file(path: Path, error_cls: type[VideoMakerError], label: str) -> str:
    """テキストファイルを読み込み、失敗時はerror_clsで分かりやすいメッセージにする。"""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise error_cls(f"{label}が見つかりません: {path}") from exc
    except IsADirectoryError as exc:
        raise error_cls(f"{label}にディレクトリが指定されています: {path}") from exc
    except PermissionError as exc:
        raise error_cls(f"{label}を読み込む権限がありません: {path}") from exc
    except UnicodeDecodeError as exc:
        raise error_cls(
            f"{label}の文字コードが不正です: {path}",
            hint="UTF-8で保存し直してください。",
        ) from exc
    except OSError as exc:
        raise error_cls(f"{label}を読み込めません: {path} ({exc})") from exc


def load_yaml_mapping(path: Path, error_cls: type[VideoMakerError], label: str) -> dict:
    """YAMLファイルを読み込み、トップレベルがマップであることを確認して返す。"""
    content = read_text_file(path, error_cls, label)
    try:
        loaded = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise error_cls(
            f"{label}のYAML形式が不正です: {path}\n  {format_yaml_error(exc)}",
            hint="インデント（半角スペース）や「キー: 値」のコロン後の空白、引用符の対応を確認してください。",
        ) from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise error_cls(
            f"{label}の形式が不正です: {path}\n  トップレベルは「キー: 値」のマップである必要があります"
        )
    return loaded
