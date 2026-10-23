"""Future TTS admission policy; importing this does not start a service.

Must run BEFORE inference on EVERY route of the actual listener. This is not
a sandbox and not a proxy in front of an unprotected second listener.
"""
from copy import deepcopy
import ipaddress
from pathlib import Path
import secrets

from .security import local_path, strict_json


LANGUAGES = frozenset({"zh", "en", "ja", "ko", "yue"})


class VoiceRequestPolicy:
    def __init__(self, reference_root, presets, *, port=9880):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("无效本地端口")
        if not isinstance(presets, dict) or not 1 <= len(presets) <= 32:
            raise ValueError("请配置1—32个本地语音预设")
        self._root = local_path(reference_root).resolve(strict=True)
        if not self._root.is_dir():
            raise ValueError("参考目录不存在")
        self._presets = deepcopy(presets)
        self._token = secrets.token_urlsafe(32)
        self._host = f"127.0.0.1:{port}"
        for name, preset in self._presets.items():
            if not isinstance(name, str) or not name or len(name) > 64:
                raise ValueError("无效语音预设编号")
            if not isinstance(preset, dict) or set(preset) != {"reference", "transcript", "language", "auxiliary"}:
                raise ValueError("语音预设字段不匹配")
            if not isinstance(preset["language"], str) or preset["language"] not in LANGUAGES:
                raise ValueError("无效参考语言")
            if not isinstance(preset["transcript"], str) or not preset["transcript"].strip() or len(preset["transcript"]) > 2000:
                raise ValueError("请填写参考音频的实际原文")
            if not isinstance(preset["auxiliary"], list) or len(preset["auxiliary"]) > 5:
                raise ValueError("辅助参考最多5段")
            self._reference(preset["reference"])
            for value in preset["auxiliary"]:
                self._reference(value)

    @property
    def authorization_header(self):
        """Pass in memory to the owned desktop client; never log or export it."""
        return "Bearer " + self._token

    def _reference(self, value):
        if not isinstance(value, str):
            raise ValueError("参考文件须为本地预设路径")
        relative = local_path(value)
        if relative.is_absolute() or ".." in value.replace("\\", "/").split("/") or ":" in value:
            raise ValueError("参考文件必须在已配置目录内")
        path = (self._root / relative).resolve(strict=True)
        if not path.is_relative_to(self._root) or not path.is_file() or path.suffix.lower() != ".wav":
            raise ValueError("参考音频超出允许目录或格式不符")
        if not 0 < path.stat().st_size <= 20_000_000:
            raise ValueError("参考文件大小不符合限制")
        return str(path)

    def admit(self, *, method, path, headers, peer, body, query=""):
        """Return a fixed engine request, never a desktop command or filepath supplied by caller."""
        try:
            loopback = ipaddress.ip_address(peer).is_loopback
        except (ValueError, TypeError):
            loopback = False
        if not loopback or method != "POST" or path != "/tts" or query:
            raise ValueError("语音接口仅允许本机POST /tts")
        if not isinstance(headers, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()):
            raise ValueError("无效请求头")
        normalized = {key.lower(): value for key, value in headers.items()}
        if len(normalized) != len(headers):
            raise ValueError("不接受重复请求头")
        if normalized.get("host") != self._host or "origin" in normalized:
            raise ValueError("不接受网页来源或其他主机")
        auth = normalized.get("authorization", "")
        if not auth.isascii() or not secrets.compare_digest(auth, self.authorization_header):
            raise ValueError("语音请求未授权")
        if normalized.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("语音请求必须为JSON")
        if not isinstance(body, bytes) or len(body) > 16_000:
            raise ValueError("语音请求超过16KB或格式不符")
        try:
            payload = strict_json(body.decode("utf-8"), max_bytes=16_000)
        except UnicodeError as exc:
            raise ValueError("语音请求必须为UTF-8") from exc
        if not isinstance(payload, dict) or set(payload) != {"voice_id", "text", "text_lang"}:
            raise ValueError("语音请求只接受预设编号、文字和语言")
        name, text, language = payload["voice_id"], payload["text"], payload["text_lang"]
        if not isinstance(name, str) or name not in self._presets:
            raise ValueError("未知语音预设")
        if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > 4000 or any(ord(c) < 32 and c not in "\n\t" for c in text):
            raise ValueError("发声文字须在4000字节内，且不含控制字符")
        if not isinstance(language, str) or language not in LANGUAGES:
            raise ValueError("不支持该文字语言")
        preset = self._presets[name]
        return {"text": text, "text_lang": language,
                "ref_audio_path": self._reference(preset["reference"]),
                "prompt_text": preset["transcript"], "prompt_lang": preset["language"],
                "aux_ref_audio_paths": [self._reference(value) for value in preset["auxiliary"]],
                "media_type": "wav", "streaming_mode": False, "batch_size": 1}
