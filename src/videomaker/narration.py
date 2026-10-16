"""ナレーション中の無音タグ（例: {無音 0.5}）の解析。

ナレーションに「{無音 秒数}」と書くと、その位置に指定した秒数の無音を入れる。
タグは字幕には表示しない。BGMは無音の間もそのまま流れる。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Union

from .textsplit import PAUSE_MARK, split_text_lines

# 無音タグ。「無音」の代わりに「mute」（大文字小文字は問わない）も使える。
# 全角の括弧・空白、末尾の「秒」「s」も許す（例: {無音 0.5}、｛無音　1秒｝、{mute 0.5}、{mute 1s}）
# タグの前後の空白（改行は除く）も一緒に取り除く
PAUSE_TAG = re.compile(
    r"[ \t　]*[{｛][ \t　]*(?:無音|(?i:mute))[ \t　]*([0-9]+(?:\.[0-9]+)?)[ \t　]*(?:秒|(?i:s))?[ \t　]*[}｝][ \t　]*"
)
# 無音タグらしいもの（書式の誤りを見つけるのに使う）
_PAUSE_LIKE = re.compile(r"[{｛][^}｝\n]*(?:無音|(?i:mute))[^}｝\n]*[}｝]")

# 合成する単位。文字列は音声合成するテキスト、数値は無音の秒数
Segment = Union[str, float]


@dataclass
class NarrationLine:
    """字幕1行分のナレーション。"""

    text: str  # 字幕に表示するテキスト（無音タグを除いたもの）
    segments: list[Segment] = field(default_factory=list)

    @property
    def has_pause(self) -> bool:
        return any(isinstance(segment, float) for segment in self.segments)

    @property
    def pause_total(self) -> float:
        return sum(segment for segment in self.segments if isinstance(segment, float))


def has_pause(text: str) -> bool:
    """無音タグを含むか。"""
    return PAUSE_TAG.search(text) is not None


def strip_pauses(text: str) -> str:
    """無音タグを取り除く（字幕の表示用）。"""
    return PAUSE_TAG.sub("", text)


def check_pause_tags(text: str) -> None:
    """書式の誤った無音タグがあれば ValueError にする。"""
    for match in _PAUSE_LIKE.finditer(text):
        if not PAUSE_TAG.fullmatch(match.group(0)):
            raise ValueError(
                f"無音の指定が不正です: {match.group(0)!r}（例: {{無音 0.5}} で0.5秒の無音）"
            )
    if has_pause(text) and not strip_pauses(text).strip():
        raise ValueError("無音だけのナレーションは書けません（無音のシーンは duration で長さを指定してください）")


def split_narration(text: str, max_chars: int) -> list[NarrationLine]:
    """ナレーションを字幕の行に分け、各行を音声合成するテキストと無音に分ける。

    行の分け方は split_text_lines と同じ（無音タグが無ければ結果の行も同じになる）。
    無音タグだけの行は、前の行の後ろ（最初の行なら次の行の前）の無音にする。
    """
    pauses: list[float] = []

    def mark(match: re.Match) -> str:
        pauses.append(float(match.group(1)))
        return PAUSE_MARK

    raw_lines = split_text_lines(PAUSE_TAG.sub(mark, text), max_chars)
    pause_iter = iter(pauses)
    result: list[NarrationLine] = []
    pending: list[Segment] = []  # 最初のテキストより前の無音
    for raw in raw_lines:
        segments: list[Segment] = []
        for i, piece in enumerate(raw.split(PAUSE_MARK)):
            if i > 0:
                segments.append(next(pause_iter))
            piece = piece.strip()
            if piece:
                segments.append(piece)
        texts = [segment for segment in segments if isinstance(segment, str)]
        if texts:
            result.append(NarrationLine(text=_join_texts(texts), segments=pending + segments))
            pending = []
        elif result:
            result[-1].segments.extend(segments)
        else:
            pending.extend(segments)
    return result


def _join_texts(texts: list[str]) -> str:
    """無音で区切ったテキストをつなげる（英単語どうしの間だけ空白を入れる）。"""
    joined = texts[0]
    for text in texts[1:]:
        if joined[-1].isascii() and joined[-1].isalnum() and text[0].isascii() and text[0].isalnum():
            joined += " "
        joined += text
    return joined
