"""長いナレーション・字幕の自動分割のテスト。"""

import yaml

from videomaker.config import AppConfig
from videomaker.models import VideoScript
from videomaker.renderer import Renderer
from videomaker.textsplit import NO_LINE_START, split_line, split_text_lines

LONG = (
    "日本では、胃の中に住み着く細菌「ヘリコバクター・ピロリ」―通称「ピロリ菌」が、"
    "少なくとも3,000万人以上の人々に感染していると考えられています。"
)


def test_short_line_is_kept() -> None:
    assert split_line("本当ですか！？　はい、そうです。", 30) == ["本当ですか！？　はい、そうです。"]


def test_split_prefers_sentence_end() -> None:
    text = "山道からはずっと八ヶ岳が望めます。雪解け水が小川となって流れています。"
    assert split_line(text, 30) == ["山道からはずっと八ヶ岳が望めます。", "雪解け水が小川となって流れています。"]


def test_split_long_text_rules() -> None:
    lines = split_line(LONG, 30)
    # 文字を失わずに分割されている
    assert "".join(lines) == LONG
    assert all(len(line) <= 30 for line in lines)
    # 「3,000」の数字の区切りでは分割しない
    assert any("3,000" in line for line in lines)
    # 読点「が、」で区切られている
    assert any(line.endswith("が、") for line in lines)
    # 行頭禁則
    assert all(line[0] not in NO_LINE_START for line in lines)


def test_split_without_punctuation_is_balanced() -> None:
    text = "句読点がまったく無い非常に長い文章でもできるだけ自然な位置で分割されて読みやすい字幕になることを確認するためのテスト文章です"
    lines = split_line(text, 30)
    assert "".join(lines) == text
    assert len(lines) == 3
    assert max(len(line) for line in lines) <= 30
    # 極端に短い行ができない
    assert min(len(line) for line in lines) >= 10


def test_closing_bracket_stays_with_sentence() -> None:
    text = "彼は「今日はとても良い天気ですね。」と言った。それから二人で長い散歩に出かけました。"
    lines = split_line(text, 20)
    assert lines[0].endswith("。」と言った。") or lines[0].endswith("。」")
    assert all(line[0] not in NO_LINE_START for line in lines)


def test_explicit_newlines_and_disable() -> None:
    assert split_text_lines("一行目\n\n二行目\n", 30) == ["一行目", "二行目"]
    assert split_text_lines(LONG, 0) == [LONG]


def test_folded_yaml_spaces_removed() -> None:
    # YAMLの「>」は改行を半角空白に変えるので、日本語の間の空白は取り除く
    text = yaml.safe_load("v: >\n  八ヶ岳が\n  望めます。\n  Hello\n  world\n")["v"]
    # 日本語と英語の間・英単語の間の空白は残す
    assert split_text_lines(text, 30) == ["八ヶ岳が望めます。 Hello world"]


def test_english_split_at_space() -> None:
    lines = split_line("The quick brown fox jumps over the lazy dog again and again", 25)
    assert all(not line.startswith(" ") and len(line) <= 25 for line in lines)
    assert " ".join(lines) == "The quick brown fox jumps over the lazy dog again and again"


# ---- 字幕・見積もりへの反映 ----

def _script(voiceover: str, duration: float = 9.0) -> VideoScript:
    return VideoScript.model_validate({
        "video": {},
        "scenes": [{"id": "s1", "image": "a.png", "duration": duration, "voiceover": voiceover}],
    })


def test_subtitle_is_split_and_timed_by_length() -> None:
    script = _script("山道からはずっと八ヶ岳が望めます。雪解け水が小川となって流れています。", duration=7.0)
    renderer = Renderer(script, config=AppConfig(subtitle_line_interval=0.0))
    clips = renderer._create_subtitle_clip(script.scenes[0], text=script.scenes[0].voiceover)
    assert len(clips) == 2
    # 17文字と18文字に比例した表示時間
    assert clips[0].duration == 7.0 * 17 / 35
    assert clips[1].start == clips[0].end


def test_subtitle_not_split_when_disabled() -> None:
    script = _script("山道からはずっと八ヶ岳が望めます。雪解け水が小川となって流れています。")
    renderer = Renderer(script, config=AppConfig(max_line_chars=0))
    clip = renderer._create_subtitle_clip(script.scenes[0], text=script.scenes[0].voiceover)
    assert not isinstance(clip, list)


def test_script_max_line_chars_overrides_config() -> None:
    # シナリオの video.max_line_chars が config より優先される（縦動画向けに短くする）
    text = "山道からはずっと八ヶ岳が望めます。"
    script = VideoScript.model_validate({
        "video": {"max_line_chars": 10},
        "scenes": [{"id": "s1", "image": "a.png", "duration": 5.0, "voiceover": text}],
    })
    renderer = Renderer(script, config=AppConfig(max_line_chars=30, subtitle_line_interval=0.0))
    clips = renderer._create_subtitle_clip(script.scenes[0], text=text)
    assert isinstance(clips, list) and len(clips) == 2


def test_script_max_line_chars_zero_disables_split() -> None:
    script = VideoScript.model_validate({"video": {"max_line_chars": 0}, "scenes": [{"id": "s1", "image": "a.png"}]})
    assert script.video.subtitle_line_chars(30) == 0
    script = VideoScript.model_validate({"video": {}, "scenes": [{"id": "s1", "image": "a.png"}]})
    assert script.video.subtitle_line_chars(30) == 30
