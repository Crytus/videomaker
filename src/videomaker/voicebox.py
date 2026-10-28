"""Voicebox API クライアント。"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import requests

from .errors import VideoMakerError
from .runlog import console


class VoiceboxError(VideoMakerError):
    """Voicebox通信エラー。"""


def clear_voice_cache(cache_dir: Path) -> tuple[int, int]:
    """音声キャッシュ(*.wav)をすべて削除し、(削除件数, 合計バイト数)を返す。

    誤設定で無関係なディレクトリを指していても被害を抑えるため、
    直下のwavファイルだけを対象にし、ディレクトリ自体は残す。
    """
    if not cache_dir.is_dir():
        return 0, 0
    count = 0
    total = 0
    for path in cache_dir.glob("*.wav"):
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
            path.unlink()
        except OSError as exc:
            raise VoiceboxError(
                f"音声キャッシュを削除できません: {path} ({exc})",
                hint="他のプログラムがファイルを使用していないか確認してください。",
            ) from exc
        total += size
        count += 1
    return count, total


class VoiceboxClient:
    """ローカルVoiceboxエンドポイントを叩くクライアント。"""

    def __init__(
        self,
        base_url: str,
        token: str | None,
        cache_dir: Path,
        timeout: float = 30.0,
        health_url: str | None = None,
        mode: str = "generic",
        voice_map: dict[str, str] | None = None,
        reading_map: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url
        self.token = token
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.health_url = health_url
        self.mode = mode
        self.voice_map = voice_map or {}
        # 長い語から順に置換し、「方法」と「方」のような重なりで短い語が先に当たらないようにする
        self.reading_map = {
            str(key): str(value)
            for key, value in sorted(
                (reading_map or {}).items(), key=lambda kv: len(str(kv[0])), reverse=True
            )
            if key
        }
        self._reading_pattern = (
            re.compile("|".join(re.escape(key) for key in self.reading_map))
            if self.reading_map
            else None
        )
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise VoiceboxError(f"音声キャッシュディレクトリを作成できません: {self.cache_dir} ({exc})") from exc

    def synthesize(
        self,
        *,
        text: str,
        voice: str | None,
        speed: float | None = None,
        pitch: float | None = None,
    ) -> Path:
        """テキストから音声ファイルを生成し、キャッシュパスを返す。"""
        text = self.apply_reading_map(text)
        resolved_voice = (
            self._resolve_voice_label(voice) if self.mode == "voicevox" else voice
        )
        cache_key = self._cache_key(
            text=text, voice=resolved_voice, speed=speed, pitch=pitch
        )
        out_path = self.cache_dir / f"{cache_key}.wav"
        if out_path.exists():
            return out_path

        if self.mode == "voicevox":
            audio_bytes = self._synthesize_voicevox(
                text=text,
                voice=resolved_voice,
                speed=speed,
                pitch=pitch,
            )
        else:
            audio_bytes = self._synthesize_generic(
                text=text,
                voice=resolved_voice,
                speed=speed,
                pitch=pitch,
            )

        if not audio_bytes:
            raise VoiceboxError(f"Voiceboxから空の音声データが返されました（テキスト: {_preview(text)}）")
        try:
            # 書き込み途中のファイルがキャッシュとして残らないよう、一時名で書いてから置き換える
            temp_path = out_path.with_suffix(".tmp")
            temp_path.write_bytes(audio_bytes)
            temp_path.replace(out_path)
        except OSError as exc:
            raise VoiceboxError(f"音声ファイルを保存できません: {out_path} ({exc})") from exc
        return out_path

    def _post(self, url: str, *, text: str, **kwargs: Any) -> requests.Response:
        """POSTリクエストを送り、通信エラーをVoiceboxErrorに変換する。"""
        try:
            return requests.post(url, timeout=self.timeout, **kwargs)
        except requests.Timeout as exc:
            raise VoiceboxError(
                f"Voiceboxの応答がタイムアウトしました（{self.timeout}秒）: {url}\n"
                f"  テキスト: {_preview(text)}",
                hint="長文の場合はconfig.yamlのvoicebox_timeoutを大きくしてください。",
            ) from exc
        except requests.ConnectionError as exc:
            raise VoiceboxError(
                f"Voiceboxに接続できません: {url}",
                hint="VOICEVOX/Voiceboxが起動しているか、config.yamlのvoicebox_urlが正しいか確認してください。",
            ) from exc
        except requests.RequestException as exc:
            raise VoiceboxError(f"Voiceboxとの通信に失敗しました: {url} ({exc})") from exc

    def apply_reading_map(self, text: str) -> str:
        """voicebox_reading_mapに従って漢字などを読みに置き換える。"""
        if self._reading_pattern is None:
            return text
        return self._reading_pattern.sub(lambda m: self.reading_map[m.group(0)], text)

    def _resolve_voice_label(self, voice: str | None) -> str | None:
        if not voice:
            return voice
        mapped = self.voice_map.get(voice)
        return mapped if mapped is not None else voice

    def _synthesize_generic(
        self,
        *,
        text: str,
        voice: str | None,
        speed: float | None,
        pitch: float | None,
    ) -> bytes:
        payload: dict[str, Any] = {"text": text}
        if voice is not None:
            payload["voice"] = voice
        if speed is not None:
            payload["speed"] = speed
        if pitch is not None:
            payload["pitch"] = pitch

        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        response = self._post(
            self.base_url,
            text=text,
            json=payload,
            headers=headers,
        )
        if response.status_code >= 400:
            raise VoiceboxError(
                f"Voiceboxエラー: {response.status_code} {response.text}"
            )
        return response.content

    def _synthesize_voicevox(
        self,
        *,
        text: str,
        voice: str | None,
        speed: float | None,
        pitch: float | None,
    ) -> bytes:
        speaker = self._voicevox_speaker_or_error(voice)
        base = self._voicevox_base_url()

        query_resp = self._post(
            f"{base}/audio_query",
            text=text,
            params={"text": text, "speaker": speaker},
        )
        if query_resp.status_code >= 400:
            raise VoiceboxError(
                f"Voicevox audio_queryエラー: {query_resp.status_code} {query_resp.text}"
            )
        try:
            query_payload = query_resp.json()
        except ValueError as exc:
            raise VoiceboxError("Voicevox audio_queryレスポンスがJSONではありません。") from exc
        if not isinstance(query_payload, dict):
            raise VoiceboxError("Voicevox audio_queryレスポンスの形式が不正です。")

        if speed is not None:
            query_payload["speedScale"] = speed
        if pitch is not None:
            query_payload["pitchScale"] = pitch

        synth_resp = self._post(
            f"{base}/synthesis",
            text=text,
            params={"speaker": speaker},
            json=query_payload,
        )
        if synth_resp.status_code >= 400:
            raise VoiceboxError(
                f"Voicevox synthesisエラー: {synth_resp.status_code} {synth_resp.text}"
            )
        return synth_resp.content

    def healthcheck(self) -> bool:
        """Voicebox APIの疎通確認。"""
        url = self._resolved_health_url()
        if url is None:
            return True
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 404 and self.health_url is None:
                console.warn(
                    "Voicebox health endpoint not found; set voicebox_health_url in "
                    "config.yaml if your server exposes a custom path."
                )
                return True
            return response.ok
        except requests.RequestException:
            return False

    def _voicevox_speaker_or_error(self, voice: str | None) -> str:
        if not voice:
            raise VoiceboxError(
                "voicevoxモードではvoice(話者ID)が必要です。video.voiceやvoice_override.voice、"
                "またはconfig.yamlのvoicebox_voice_mapで話者IDを設定してください。"
            )
        speaker = str(voice)
        if not speaker.isdigit():
            raise VoiceboxError(
                "voicevoxモードでは数値の話者IDが必要です。voicebox_voice_mapでエイリアスをIDに"
                "変換するか、story.yamlのvoiceに直接IDを記載してください。"
            )
        return speaker

    def _voicevox_base_url(self) -> str:
        base = self.base_url.rstrip("/")
        for suffix in ("/synthesis", "/audio_query", "/tts"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        return base

    def _resolved_health_url(self) -> str | None:
        if self.health_url:
            return self.health_url
        if self.mode == "voicevox":
            return f"{self._voicevox_base_url()}/speakers"
        if "/tts" not in self.base_url:
            return None
        return self.base_url.replace("/tts", "/health")

    def _cache_key(self, **payload: Any) -> str:
        raw = repr(sorted(payload.items())).encode("utf-8")
        return hashlib.sha1(raw).hexdigest()


def _preview(text: str, limit: int = 30) -> str:
    """エラーメッセージ用にテキストを短く切り詰める。"""
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"
