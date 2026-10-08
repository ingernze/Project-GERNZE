"""DeepSeek key storage in the current Windows user's Credential Manager."""
from __future__ import annotations

import pywintypes
import win32cred

TARGET = "HecatePixelPet/DeepSeek/TrialV01"


def get_key() -> str | None:
    try:
        credential = win32cred.CredRead(TARGET, win32cred.CRED_TYPE_GENERIC, 0)
    except pywintypes.error as exc:
        if exc.winerror == 1168:  # ERROR_NOT_FOUND
            return None
        raise
    blob = credential.get("CredentialBlob")
    if isinstance(blob, bytes):
        return blob.decode("utf-16-le")
    return blob or None


def save_key(key: str) -> None:
    key = key.strip()
    if not key:
        raise ValueError("密钥不能为空")
    win32cred.CredWrite({
        "Type": win32cred.CRED_TYPE_GENERIC,
        "TargetName": TARGET,
        "CredentialBlob": key,
        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        "UserName": "DeepSeek API",
    }, 0)


def delete_key() -> None:
    try:
        win32cred.CredDelete(TARGET, win32cred.CRED_TYPE_GENERIC, 0)
    except pywintypes.error as exc:
        if exc.winerror != 1168:
            raise
