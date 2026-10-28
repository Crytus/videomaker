"""YAMLスクリプトファイルの読み込みと検証を担当する。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .errors import ScriptError, format_validation_error, load_yaml_mapping
from .models import VideoScript
from .runlog import console


PATH_KEYS = {
    ("video", "bgm"),
    ("video", "subtitle", "font"),
    ("options", "voice_cache_dir"),
    ("scenes", "*", "image"),
    ("scenes", "*", "video"),
}


def parse_script(script_path: Path) -> VideoScript:
    """YAMLファイルからVideoScriptを構築する。"""
    data = load_yaml_mapping(script_path, ScriptError, "スクリプト")
    resolved = _resolve_paths(data, base_dir=script_path.parent)
    try:
        return VideoScript.model_validate(resolved)
    except ValidationError as exc:
        raise ScriptError(
            f"スクリプトの内容が不正です: {script_path}\n{format_validation_error(exc)}",
            hint="README.md のYAML設定項目の説明を参考に修正してください。",
        ) from exc


def _resolve_paths(data: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    """特定キーの値をPath化し、相対パスであればファイル基準に解決する。"""

    def resolver(key_path: tuple[str, ...], value: Any) -> Any:
        if not isinstance(value, str):
            return value
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = (base_dir / candidate).resolve()
        return str(candidate)

    def recurse(node: Any, path: tuple[str, ...]) -> Any:
        if isinstance(node, dict):
            new_dict: dict[str, Any] = {}
            for key, value in node.items():
                child_path = path + (str(key),)
                new_dict[key] = recurse(value, child_path)
            return new_dict
        if isinstance(node, list):
            return [recurse(value, path + ("*",)) for value in node]

        if _path_match(path):
            return resolver(path, node)
        return node

    return recurse(data, ())


def _path_match(path: tuple[str, ...]) -> bool:
    for target in PATH_KEYS:
        if len(target) != len(path):
            continue
        for actual, expected in zip(path, target, strict=False):
            if expected == "*":
                continue
            if actual != expected:
                break
        else:
            return True
    return False
