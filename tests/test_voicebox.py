from pathlib import Path

from videomaker.config import AppConfig
from videomaker.voicebox import VoiceboxClient


def _client(tmp_path: Path, **kwargs) -> VoiceboxClient:
    return VoiceboxClient(base_url="http://localhost/api/tts", token=None, cache_dir=tmp_path, **kwargs)


def test_reading_map_replaces_text(tmp_path: Path) -> None:
    client = _client(tmp_path, reading_map={"方": "かた", "方法": "ほうほう"})
    assert client.apply_reading_map("この方の方法") == "このかたのほうほう"


def test_reading_map_empty_is_noop(tmp_path: Path) -> None:
    client = _client(tmp_path, reading_map={"": "x"})
    assert client.apply_reading_map("方") == "方"


def test_config_timeout_and_reading_map() -> None:
    config = AppConfig.model_validate(
        {"voicebox_timeout": 120, "voicebox_reading_map": {"方": "かた"}}
    )
    assert config.voicebox_timeout == 120
    assert config.voicebox_reading_map == {"方": "かた"}
    assert AppConfig().voicebox_timeout == 30.0
