"""Bounded data parsing and explicit local exports. No listener or worker."""
import json
import math
from pathlib import Path
import re


def strict_json(text, *, max_bytes, max_depth=24):
    """Reject duplicate keys, huge numbers, non-finite values and deep input."""
    if not isinstance(text, str) or len(text.encode("utf-8")) > max_bytes:
        raise ValueError(f"JSON文字须在{max_bytes}字节内")
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > max_depth:
                raise ValueError("JSON嵌套过深")
        elif char in "]}":
            depth -= 1

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("JSON包含重复字段")
            value[key] = item
        return value

    def integer(raw):
        if len(raw.lstrip("-")) > 19:
            raise ValueError("JSON整数过长")
        return int(raw)

    def number(raw):
        if len(raw) > 64:
            raise ValueError("JSON数字过长")
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError("JSON不允许非有限数字")
        return value

    def constant(_raw):
        raise ValueError("JSON不允许非有限数字")

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_int=integer,
                          parse_float=number, parse_constant=constant)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("不是有效JSON，请按原模板重新整理") from exc


def local_path(value):
    """Disallow URLs, network/device paths and Windows alternate data streams."""
    raw = str(value)
    if not raw or any(ord(char) < 32 for char in raw):
        raise ValueError("请选择有效本地路径")
    windows = raw.replace("/", "\\")
    if windows.startswith("\\\\") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", raw):
        raise ValueError("只允许本地文件，不接受网络或设备路径")
    tail = windows[2:] if re.match(r"^[A-Za-z]:", windows) else windows
    if ":" in tail or (re.match(r"^[A-Za-z]:", windows) and not tail.startswith("\\")):
        raise ValueError("不接受设备流或相对盘符路径")
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update(f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10))
    reserved.update(f"{prefix}{i}" for prefix in ("COM", "LPT") for i in "¹²³")
    for part in tail.split("\\"):
        if part in {"", ".", ".."}:
            continue
        if part.rstrip(" .") != part or part.split(".")[0].upper() in reserved:
            raise ValueError("不接受Windows保留文件名")
    return Path(raw)


def export_destination(value, *, suffixes, protected_paths=()):
    path = local_path(value)
    if path.suffix.lower() not in suffixes:
        raise ValueError("请使用约定的导出文件扩展名")
    resolved = path.resolve()
    if any(resolved == Path(item).resolve() for item in protected_paths):
        raise ValueError("导出不能覆盖当前数据文件")
    if path.exists() or path.is_symlink():
        raise ValueError("请选择一个尚不存在的导出或备份文件")
    return path


def write_export(destination, content, *, suffix, protected_paths=()):
    """UI-selected new file only; exclusive create also covers existence races."""
    if not isinstance(content, str):
        raise ValueError("导出内容必须是文字")
    path = export_destination(destination, suffixes={suffix}, protected_paths=protected_paths)
    created = False
    try:
        with path.open("x", encoding="utf-8") as stream:
            created = True
            stream.write(content)
    except Exception:
        if created:
            path.unlink(missing_ok=True)
        raise
    return path
