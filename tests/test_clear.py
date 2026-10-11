from pathlib import Path

from typer.testing import CliRunner

from videomaker.cli import app
from videomaker.voicebox import clear_voice_cache

runner = CliRunner()


def _make_cache(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "abc.wav").write_bytes(b"x" * 10)
    (cache_dir / "combined_def.wav").write_bytes(b"y" * 20)
    (cache_dir / "keep.txt").write_text("wav以外は残す", encoding="utf-8")


def test_clear_voice_cache_removes_only_wav(tmp_path: Path) -> None:
    _make_cache(tmp_path)
    assert clear_voice_cache(tmp_path) == (2, 30)
    assert not list(tmp_path.glob("*.wav"))
    assert (tmp_path / "keep.txt").exists()


def test_clear_voice_cache_missing_dir(tmp_path: Path) -> None:
    assert clear_voice_cache(tmp_path / "none") == (0, 0)


def test_cli_clear_with_yes(tmp_path: Path) -> None:
    _make_cache(tmp_path)
    result = runner.invoke(app, ["clear", "--voice-cache", str(tmp_path), "-y"])
    assert result.exit_code == 0, result.output
    assert not list(tmp_path.glob("*.wav"))


def test_cli_clear_abort_keeps_files(tmp_path: Path) -> None:
    _make_cache(tmp_path)
    result = runner.invoke(app, ["clear", "--voice-cache", str(tmp_path)], input="n\n")
    assert result.exit_code != 0
    assert len(list(tmp_path.glob("*.wav"))) == 2


def test_cli_clear_empty(tmp_path: Path) -> None:
    result = runner.invoke(app, ["clear", "--voice-cache", str(tmp_path)])
    assert result.exit_code == 0
