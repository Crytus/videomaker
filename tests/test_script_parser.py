from pathlib import Path

from videomaker.script_parser import parse_script


def test_parse_script_resolves_relative_paths(tmp_path: Path) -> None:
    sample = Path("samples/story.yaml")
    script = parse_script(sample)

    assert script.video.width == 1920
    assert script.scenes[0].image.is_absolute()
    assert script.options.voice_cache_dir.is_absolute()
