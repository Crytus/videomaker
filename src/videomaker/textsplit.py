"""長いナレーション・字幕を、読みやすい長さの行に自動分割する。

分割の優先順位:
1. 文末の句読点（。！？）
2. 読点など（、，；：。「3,000」のような数字の区切りは除く）
3. 空白
4. 括弧の前後
5. ひらがな→漢字・カタカナの境目（文節の切れ目になりやすい）
同じ優先度なら、行の長さができるだけ均等になる位置を選ぶ。

行頭禁則（句読点・閉じ括弧・小書きの仮名・長音で行が始まらない）を守る。
"""

from __future__ import annotations

import math
import re

SENTENCE_END = "。．！？!?"
CLAUSE_END = "、，,；;：:"
CLOSERS = "」』）)】〕］]｝}〉》”’\"'"
OPENERS = "「『（(【〔［[｛{〈《“‘"
# ナレーション中の無音タグ（{無音 0.5}）の位置を表す文字（narration.py で使う私用領域の文字）
PAUSE_MARK = ""
# 行頭に来てはいけない文字
NO_LINE_START = (
    CLOSERS + SENTENCE_END + CLAUSE_END + "ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶー・…‥〜～"
)

# YAMLの「>」で折り返した行は半角空白で連結されるため、日本語の文字に挟まれた空白は取り除く
_JA_CHAR = r"[　-ヿ㐀-鿿豈-﫿＀-￯]"
_JA_SPACE = re.compile(rf"(?<={_JA_CHAR}) +(?={_JA_CHAR})")


def split_text_lines(text: str, max_chars: int) -> list[str]:
    """テキストを行のリストにする。max_charsを超える行は自動で分割する（0以下なら分割しない）。"""
    lines = [_JA_SPACE.sub("", line.strip()) for line in text.split("\n") if line.strip()]
    if max_chars <= 0:
        return lines
    result: list[str] = []
    for line in lines:
        result.extend(split_line(line, max_chars))
    return result


def split_line(line: str, max_chars: int) -> list[str]:
    """1行をmax_chars程度の長さに分割する。

    残りの文字数を均等に分けた長さを目標にし、その前後で最も優先度の高い切れ目
    （句点 > 読点 > 空白 > 括弧 > 文節らしい境目）を選ぶ。同じ優先度なら目標に近い位置を選ぶ。
    """
    parts = []
    remaining = line
    while len(remaining) > max_chars:
        # 最後の行だけ極端に短くならないよう、残りを均等に分けた長さを目標にする
        count = math.ceil(len(remaining) / max_chars)
        target = math.ceil(len(remaining) / count)
        cut = _find_cut(remaining, target, max_chars)
        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def _find_cut(text: str, target: int, max_chars: int) -> int:
    """分割位置（この位置の文字から次の行）を選ぶ。"""
    best = None
    best_key = None
    low = max(1, int(target * 0.4))
    for pos in range(low, min(max_chars, len(text) - 1) + 1):
        if text[pos] in NO_LINE_START:
            continue
        key = (_boundary_score(text, pos), -abs(pos - target))
        if best_key is None or key > best_key:
            best, best_key = pos, key
    if best is not None:
        return best
    # 禁則文字ばかりの場合は、行頭禁則を外れる位置まで後ろにずらす
    pos = min(target, len(text) - 1)
    while pos < len(text) - 1 and text[pos] in NO_LINE_START:
        pos += 1
    return pos


def _boundary_score(text: str, pos: int) -> int:
    """posの直前で区切ったときの切れ目らしさ（大きいほど優先）。"""
    prev, cur = text[pos - 1], text[pos]
    # 「。」」のように句読点の後に閉じ括弧が続く場合は、句読点の位置で判定する
    k = pos - 1
    while k > 0 and text[k] in CLOSERS:
        k -= 1
    mark = text[k]
    if mark in SENTENCE_END:
        return 5
    if mark in CLAUSE_END and not _is_number_separator(text, k):
        return 4
    if prev == PAUSE_MARK:
        # 無音の直後は読点と同じくらい区切りやすい
        return 4
    if prev.isspace() or cur.isspace():
        return 3
    if prev in CLOSERS or cur in OPENERS:
        return 2
    if _is_hiragana(prev) and not _is_hiragana(cur):
        return 1
    return 0


def _is_number_separator(text: str, index: int) -> bool:
    """「3,000」「1:30」のような数字の区切りか。"""
    return 0 < index < len(text) - 1 and text[index - 1].isdigit() and text[index + 1].isdigit()


def _is_hiragana(char: str) -> bool:
    return "\u3041" <= char <= "\u309f"
