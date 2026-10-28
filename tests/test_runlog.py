"""実行ログ（ログファイルへの出力と警告の案内）のテスト。"""

import warnings
from pathlib import Path

from typer.testing import CliRunner

from videomaker import runlog
from videomaker.cli import app

runner = CliRunner()


def _read_single_log(log_dir: Path) -> str:
    logs = list(log_dir.glob("*.log"))
    assert len(logs) == 1
    return logs[0].read_text(encoding="utf-8")


def test_session_writes_console_output_and_counts_warnings(tmp_path: Path) -> None:
    session = runlog.start_session(tmp_path, "test")
    try:
        runlog.console.log("[cyan]通常のメッセージ[/]")
        runlog.console.warn("BGMが短い")
        warnings.warn("moviepy風の警告", UserWarning)
    finally:
        ended = runlog.end_session()

    assert ended is session
    assert session.warning_count == 1
    assert session.python_warnings == 1
    assert session.total_warnings == 2
    text = session.path.read_text(encoding="utf-8")
    assert "通常のメッセージ" in text
    assert "警告: BGMが短い" in text
    assert "UserWarning" in text and "moviepy風の警告" in text
    # 色指定などのマークアップやエスケープシーケンスは残さない
    assert "[cyan]" not in text and "\x1b[" not in text
    # 呼び出し元のファイル名が記録される
    assert "test_runlog.py" in text


def test_python_warning_is_not_shown_on_screen(tmp_path: Path, capsys) -> None:
    runlog.start_session(tmp_path, "test")
    try:
        warnings.warn("画面に出ない警告", UserWarning)
    finally:
        runlog.end_session()
    captured = capsys.readouterr()
    assert "画面に出ない警告" not in captured.out + captured.err


def test_similar_python_warnings_are_merged(tmp_path: Path) -> None:
    session = runlog.start_session(tmp_path, "test")
    try:
        for i in range(10):
            warnings.warn(f"0 bytes read at frame index {i} at time {i / 24:.2f}", UserWarning)
        warnings.warn("別の警告", UserWarning)
    finally:
        runlog.end_session()
    assert session.python_warnings == 2
    text = session.path.read_text(encoding="utf-8")
    assert text.count("bytes read at frame index") == 2  # 最初の1件と終了時のまとめ
    assert "同じ種類の警告が 10 回発生しました" in text


def test_showwarning_restored_after_session(tmp_path: Path) -> None:
    original = warnings.showwarning
    runlog.start_session(tmp_path, "test")
    assert warnings.showwarning is not original
    runlog.end_session()
    assert warnings.showwarning is original


def test_no_output_to_file_without_session(tmp_path: Path) -> None:
    assert runlog.current_session() is None
    runlog.console.warn("セッション外の警告")  # 例外にならないこと


def test_old_logs_are_pruned(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runlog, "KEEP_LOG_FILES", 3)
    for i in range(5):
        (tmp_path / f"20200101_00000{i}_old.log").write_text("", encoding="utf-8")
    session = runlog.start_session(tmp_path, "new")
    runlog.end_session()
    names = sorted(p.name for p in tmp_path.glob("*.log"))
    assert len(names) == 3
    assert session.path.name in names
    assert "20200101_000000_old.log" not in names


def test_cli_reports_warnings_at_end(tmp_path: Path, monkeypatch) -> None:
    log_dir = tmp_path / "logs"

    def fake_validate(self) -> None:
        runlog.console.warn("確認してほしい問題")

    monkeypatch.setattr("videomaker.pipeline.VideoPipeline.validate", fake_validate)
    script = tmp_path / "story.yaml"
    script.write_text("video: {}\nscenes:\n  - id: s1\n    image: a.png\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("", encoding="utf-8")

    result = runner.invoke(
        app, ["--log-dir", str(log_dir), "validate", str(script), "--config", str(config)]
    )
    assert result.exit_code == 0, result.output
    assert "警告が 1 件ありました" in result.output
    text = _read_single_log(log_dir)
    assert "確認してほしい問題" in text
    assert "検証が完了しました" in text
    assert next(log_dir.glob("*.log")).name.endswith("_validate_story.log")


def test_cli_no_message_without_warnings(tmp_path: Path, monkeypatch) -> None:
    log_dir = tmp_path / "logs"
    monkeypatch.setattr("videomaker.pipeline.VideoPipeline.validate", lambda self: None)
    script = tmp_path / "story.yaml"
    script.write_text("video: {}\nscenes:\n  - id: s1\n    image: a.png\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("", encoding="utf-8")

    result = runner.invoke(
        app, ["--log-dir", str(log_dir), "validate", str(script), "--config", str(config)]
    )
    assert result.exit_code == 0, result.output
    assert "警告が" not in result.output
    assert "ログファイル" not in result.output
    assert len(list(log_dir.glob("*.log"))) == 1


def test_cli_error_traceback_goes_to_log_file(tmp_path: Path, monkeypatch) -> None:
    log_dir = tmp_path / "logs"

    def boom(*args, **kwargs):
        raise RuntimeError("想定外")

    monkeypatch.setattr("videomaker.cli.load_config", boom)
    script = tmp_path / "story.yaml"
    script.write_text("video: {}\nscenes: []\n", encoding="utf-8")

    result = runner.invoke(app, ["--log-dir", str(log_dir), "validate", str(script)])
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "ログファイル" in result.output
    text = _read_single_log(log_dir)
    assert "Traceback" in text and "想定外" in text
