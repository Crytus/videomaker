"""テスト全体の共通設定。"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_log_dir(tmp_path_factory, monkeypatch):
    # CLIのテストで実行ログがリポジトリ内の logs/ に作られないようにする
    monkeypatch.setenv("VIDEOMAKER_LOG_DIR", str(tmp_path_factory.mktemp("logs")))
