"""例外発生時に分かりやすいエラーメッセージになることを確認するテスト。"""

from pathlib import Path

import pytest
import requests
from typer.testing import CliRunner

from videomaker import voicebox as voicebox_module
from videomaker.cli import app
from videomaker.config import load_config
from videomaker.errors import AssetError, ConfigError, ScriptError, VideoMakerError
from videomaker.models import VideoScript
from videomaker.renderer import Renderer, _load_media
from videomaker.script_parser import parse_script
from videomaker.voicebox import VoiceboxClient, VoiceboxError

runner = CliRunner()

VALID_SCRIPT = """\
video:
  width: 320
  height: 240
scenes:
  - id: s1
    image: {image}
    voiceover: こんにちは
"""


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# ---- 設定ファイル ----

def test_config_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="設定ファイルが見つかりません"):
        load_config(tmp_path / "none.yaml")


def test_config_yaml_syntax_error_has_line(tmp_path: Path) -> None:
    path = _write(tmp_path / "config.yaml", "voicebox_url: http://x\nvoicebox_timeout: [1, 2\n")
    with pytest.raises(ConfigError, match="YAML形式が不正です") as info:
        load_config(path)
    assert "行目" in str(info.value)
    assert info.value.hint


def test_config_not_mapping(tmp_path: Path) -> None:
    path = _write(tmp_path / "config.yaml", "- a\n- b\n")
    with pytest.raises(ConfigError, match="マップである必要があります"):
        load_config(path)


def test_config_invalid_value(tmp_path: Path) -> None:
    path = _write(tmp_path / "config.yaml", "voicebox_timeout: abc\nvoicebox_mode: foo\n")
    with pytest.raises(ConfigError) as info:
        load_config(path)
    message = str(info.value)
    assert "voicebox_timeout: 数値を指定してください" in message
    assert "voicebox_mode" in message


def test_config_bad_encoding(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes("voicebox_url: あ\n".encode("cp932"))
    with pytest.raises(ConfigError, match="文字コード"):
        load_config(path)


def test_config_empty_file_uses_defaults(tmp_path: Path) -> None:
    path = _write(tmp_path / "config.yaml", "")
    assert load_config(path).voicebox_timeout == 30.0


# ---- スクリプト ----

def test_script_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ScriptError, match="スクリプトが見つかりません"):
        parse_script(tmp_path / "none.yaml")


def test_script_yaml_syntax_error(tmp_path: Path) -> None:
    path = _write(tmp_path / "story.yaml", "video:\n  width: 320\n scenes: x\n")
    with pytest.raises(ScriptError, match="YAML形式が不正です"):
        parse_script(path)


def test_script_missing_required_fields(tmp_path: Path) -> None:
    path = _write(tmp_path / "story.yaml", "video: {}\nscenes:\n  - id: s1\n    image: a.png\n")
    with pytest.raises(ScriptError) as info:
        parse_script(path)
    assert "scenes.0.voiceover: 必須項目がありません" in str(info.value)


def test_script_custom_validator_message(tmp_path: Path) -> None:
    path = _write(tmp_path / "story.yaml", "video: {}\nscenes:\n  - id: s1\n    voiceover: x\n")
    with pytest.raises(ScriptError) as info:
        parse_script(path)
    assert "image または video のいずれかが必要です" in str(info.value)
    assert "Value error" not in str(info.value)


# ---- Voicebox ----

def _client(tmp_path: Path) -> VoiceboxClient:
    return VoiceboxClient(base_url="http://127.0.0.1:1/api/tts", token=None, cache_dir=tmp_path, timeout=3)


def test_voicebox_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(voicebox_module.requests, "post", fake_post)
    with pytest.raises(VoiceboxError, match="タイムアウト") as info:
        _client(tmp_path).synthesize(text="テスト", voice=None)
    assert "voicebox_timeout" in info.value.hint
    # 失敗時にキャッシュファイルが残らないこと
    assert not list(tmp_path.iterdir())


def test_voicebox_connection_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(*args, **kwargs):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(voicebox_module.requests, "post", fake_post)
    with pytest.raises(VoiceboxError, match="接続できません"):
        _client(tmp_path).synthesize(text="テスト", voice=None)


# ---- レンダラー ----

def test_load_media_broken_file(tmp_path: Path) -> None:
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")

    def loader():
        from PIL import Image

        return Image.open(broken)

    with pytest.raises(AssetError, match="画像ファイルを読み込めません"):
        _load_media(loader, "s1", "画像", broken)


def test_select_unknown_scene(tmp_path: Path) -> None:
    script = VideoScript.model_validate(
        {"video": {}, "scenes": [{"id": "s1", "image": "a.png", "voiceover": "x"}]}
    )
    with pytest.raises(VideoMakerError, match="シーンが見つかりません") as info:
        Renderer(script)._select_scenes(["nope"])
    assert "s1" in info.value.hint


# ---- CLI ----

def test_cli_validate_reports_script_error(tmp_path: Path) -> None:
    script = _write(tmp_path / "story.yaml", "video: [\n")
    result = runner.invoke(app, ["validate", str(script)])
    assert result.exit_code == 1
    assert "エラー:" in result.output
    assert "YAML形式が不正です" in result.output
    assert "Traceback" not in result.output


def test_cli_validate_reports_missing_assets(tmp_path: Path) -> None:
    script = _write(tmp_path / "story.yaml", VALID_SCRIPT.format(image="missing_image.png"))
    config = _write(tmp_path / "config.yaml", "")
    result = runner.invoke(app, ["validate", str(script), "--config", str(config)])
    assert result.exit_code == 1
    assert "素材ファイルが見つかりません" in result.output
    assert "missing_image.png" in result.output
    assert "ヒント:" in result.output


def test_cli_missing_config(tmp_path: Path) -> None:
    script = _write(tmp_path / "story.yaml", VALID_SCRIPT.format(image="a.png"))
    result = runner.invoke(app, ["validate", str(script), "--config", str(tmp_path / "none.yaml")])
    assert result.exit_code == 1
    assert "設定ファイルが見つかりません" in result.output


def test_cli_unexpected_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("想定外")

    monkeypatch.setattr("videomaker.cli.load_config", boom)
    script = _write(tmp_path / "story.yaml", VALID_SCRIPT.format(image="a.png"))
    result = runner.invoke(app, ["validate", str(script)])
    assert result.exit_code == 1
    assert "予期しないエラー" in result.output
    assert "--debug" in result.output

    result = runner.invoke(app, ["--debug", "validate", str(script)])
    assert result.exit_code == 1
    assert "Traceback" in result.output
