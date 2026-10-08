"""Small local command registry. No model, transport, queue or worker."""
from copy import deepcopy
from dataclasses import dataclass
import json
from _thread import get_ident
from typing import Callable


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate(value, schema, path="参数"):
    kind = schema["type"]
    types = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
             "object": dict, "array": list, "null": type(None)}
    if kind not in types:
        raise ValueError(f"未知格式类型：{kind}")
    if not isinstance(value, types[kind]) or (kind in {"integer", "number"} and isinstance(value, bool)):
        raise ValueError(f"{path}须为{kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}的值不在允许列表内")
    if kind == "string" and "maxLength" in schema and len(value) > schema["maxLength"]:
        raise ValueError(f"{path}过长")
    if kind == "array":
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ValueError(f"{path}项目过多")
        if "items" in schema:
            for i, item in enumerate(value):
                validate(item, schema["items"], f"{path}[{i}]")
    if kind == "object":
        if any(not isinstance(k, str) for k in value):
            raise ValueError(f"{path}字段名须为文字")
        props = schema.get("properties")
        if props is not None:
            for key in schema.get("required", []):
                if key not in value:
                    raise ValueError(f"{path}缺少{key}")
            if not schema.get("additionalProperties", False):
                unknown = value.keys() - props.keys()
                if unknown:
                    raise ValueError(f"{path}包含未约定字段：{', '.join(sorted(unknown))}")
            for key, item in value.items():
                if key in props:
                    validate(item, props[key], f"{path}.{key}")


def parameters(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    output: dict
    execute: Callable


class ToolRegistry:
    def __init__(self):
        self._tools = {}
        self._thread = get_ident()
        self._closed = False

    def register(self, tool, owner):
        if self._closed:
            raise ValueError("工具入口已关闭")
        if get_ident() != self._thread:
            raise ValueError("工具注册须在创建入口的线程执行")
        if not isinstance(tool, Tool) or not tool.name or not owner or not callable(tool.execute):
            raise ValueError("工具须包含名称、归属和执行函数")
        if tool.name in self._tools:
            raise ValueError(f"工具名称重复：{tool.name}")
        self._tools[tool.name] = (Tool(tool.name, tool.description, deepcopy(tool.parameters), deepcopy(tool.output), tool.execute), owner)

    def schemas(self):
        # Inspection returns data, never execute functions or owner internals.
        return [{"name": t.name, "description": t.description, "parameters": deepcopy(t.parameters), "output": deepcopy(t.output)}
                for t, _ in self._tools.values()]

    def unregister_owner(self, owner):
        if get_ident() != self._thread:
            raise ValueError("工具卸载须在创建入口的线程执行")
        self._tools = {name: pair for name, pair in self._tools.items() if pair[1] != owner}

    def call(self, name, arguments):
        def error(code, message):
            return {"ok": False, "tool": name, "error": {"code": code, "message": message}}
        if get_ident() != self._thread:
            return error("WRONG_THREAD", "请通过主程序现有事件通知，在创建工具入口的线程调用")
        if self._closed:
            return error("CLOSED", "工具入口已关闭")
        if not isinstance(name, str) or name not in self._tools:
            return error("UNKNOWN_TOOL", "找不到已注册工具")
        tool, _ = self._tools[name]
        try:
            if len(canonical(arguments).encode("utf-8")) > 600_000:
                raise ValueError("参数超过600KB")
            validate(arguments, tool.parameters)
            args = deepcopy(arguments)
        except (ValueError, TypeError, RecursionError) as exc:
            return error("INVALID_ARGUMENT", str(exc))
        try:
            result = tool.execute(args)
        except Exception as exc:
            return error("EXECUTION_FAILED", str(exc))
        try:
            validate(result, tool.output, "返回值")
            # Explicit full-data/Markdown exports may legitimately be large.
            # Strings are already canonical JSON values; nested results still
            # need this check for NaN and non-JSON Python objects.
            if not isinstance(result, str):
                canonical(result)
        except (ValueError, TypeError, RecursionError) as exc:
            return error("INVALID_RESULT", str(exc))
        return {"ok": True, "tool": name, "data": result}

    def close(self):
        if get_ident() != self._thread:
            raise ValueError("工具入口须在创建线程关闭")
        self._tools.clear()
        self._closed = True
