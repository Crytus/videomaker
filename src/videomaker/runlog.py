"""実行ログの管理。

画面に出したメッセージをログファイルにも書き出し、実行を止めるほどではない問題（警告）を
件数として数える。Python の warnings（moviepy が出す UserWarning など）は進捗表示を
崩さないよう画面には出さず、ログファイルにだけ記録する。
"""

from __future__ import annotations

import re
import sys
import traceback
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Optional

from rich.console import Console
from rich.markup import escape

# ログファイルの1行の幅（画面幅に左右されないよう固定する）
LOG_WIDTH = 160
# ログディレクトリに残すログファイルの数（古いものから削除する）
KEEP_LOG_FILES = 30


@dataclass
class RunLogSession:
    """1回の実行に対応するログファイルの状態。"""

    path: Path
    stream: IO[str]
    file_console: Console
    warning_count: int = 0
    # Python の警告。数字だけが異なる同じ種類の警告（フレーム番号違いなど）は1件にまとめる
    # キー: (種類, 数字を伏せたメッセージ)、値: [発生回数, 最初のメッセージ]
    python_warning_kinds: dict[tuple[str, str], list] = field(default_factory=dict)
    _saved_showwarning: Any = field(default=None, repr=False)

    @property
    def python_warnings(self) -> int:
        """Python の警告の種類数。"""
        return len(self.python_warning_kinds)

    @property
    def total_warnings(self) -> int:
        return self.warning_count + self.python_warnings


_session: Optional[RunLogSession] = None


def current_session() -> Optional[RunLogSession]:
    return _session


class LogConsole(Console):
    """画面への出力と同じ内容を、実行中のログファイルにも書き出すConsole。"""

    def print(self, *objects: Any, **kwargs: Any) -> None:  # type: ignore[override]
        super().print(*objects, **kwargs)
        if _session is not None:
            _session.file_console.print(*objects, **kwargs)

    def log(self, *objects: Any, _stack_offset: int = 1, **kwargs: Any) -> None:  # type: ignore[override]
        # 呼び出し元のファイル名・行番号が表示されるよう、このメソッドの分だけ遡る
        super().log(*objects, _stack_offset=_stack_offset + 1, **kwargs)
        if _session is not None:
            _session.file_console.log(*objects, _stack_offset=_stack_offset + 1, **kwargs)

    def warn(self, message: str, *, _stack_offset: int = 1) -> None:
        """実行は続けられる問題を警告として表示・記録する（終了時に件数を案内する）。

        message は rich のマークアップとして解釈される。
        """
        super().log(f"[yellow]{message}[/]", _stack_offset=_stack_offset + 1)
        if _session is not None:
            _session.warning_count += 1
            _session.file_console.log(f"警告: {message}", _stack_offset=_stack_offset + 1)


# 各モジュールで共有するConsole
console = LogConsole()
error_console = LogConsole(stderr=True)


def _showwarning(message, category, filename, lineno, file=None, line=None) -> None:
    """warnings.warn の出力先をログファイルに差し替える。"""
    session = _session
    if session is None:
        return
    key = (category.__name__, re.sub(r"\d+(?:\.\d+)?", "#", str(message)))
    entry = session.python_warning_kinds.setdefault(key, [0, str(message)])
    entry[0] += 1
    if entry[0] > 1:
        # 2件目以降は記録せず、終了時に件数だけまとめて書き出す
        return
    text = f"警告 ({category.__name__}): {message}  [{filename}:{lineno}]"
    session.file_console.print(escape(text), highlight=False)


def _prune_old_logs(log_dir: Path, keep: int) -> None:
    """古いログファイルを削除して、新しいものから keep 件だけ残す。"""
    logs = sorted(log_dir.glob("*.log"), key=lambda p: p.name, reverse=True)
    for old in logs[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def start_session(log_dir: Path, name: str, *, argv: Optional[list[str]] = None) -> RunLogSession:
    """ログファイルを作成し、以降の出力をそこにも書き出す。"""
    global _session
    if _session is not None:
        end_session()

    log_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    path = log_dir / f"{now:%Y%m%d_%H%M%S}_{name}.log"
    # 同じ秒に複数回実行した場合に上書きしないよう連番を付ける
    serial = 1
    while path.exists():
        path = log_dir / f"{now:%Y%m%d_%H%M%S}_{name}_{serial}.log"
        serial += 1

    stream = path.open("w", encoding="utf-8")
    file_console = Console(
        file=stream,
        color_system=None,
        force_terminal=False,
        force_jupyter=False,
        width=LOG_WIDTH,
        log_time_format="[%H:%M:%S]",
        emoji=False,
    )
    session = RunLogSession(path=path, stream=stream, file_console=file_console)
    file_console.print(f"VideoMaker 実行ログ  {now:%Y-%m-%d %H:%M:%S}", highlight=False)
    file_console.print(f"コマンド: {escape(' '.join(argv if argv is not None else sys.argv))}", highlight=False)
    file_console.rule()

    session._saved_showwarning = warnings.showwarning
    warnings.showwarning = _showwarning
    _session = session
    _prune_old_logs(log_dir, KEEP_LOG_FILES)
    return session


def log_exception() -> None:
    """処理中の例外のトレースバックをログファイルにだけ書き出す（画面には出さない）。"""
    if _session is None:
        return
    _session.file_console.print(escape(traceback.format_exc()), highlight=False)


def end_session() -> Optional[RunLogSession]:
    """ログファイルを閉じて、終了したセッションを返す。"""
    global _session
    session = _session
    if session is None:
        return None
    session.file_console.rule()
    for (category, _), (count, message) in session.python_warning_kinds.items():
        if count > 1:
            session.file_console.print(
                escape(f"同じ種類の警告が {count} 回発生しました ({category}、最初の1件): {message}"), highlight=False
            )
    session.file_console.print(
        f"警告: {session.warning_count} 件 / Python の警告: {session.python_warnings} 種類",
        highlight=False,
    )
    warnings.showwarning = session._saved_showwarning
    _session = None
    session.stream.close()
    return session
