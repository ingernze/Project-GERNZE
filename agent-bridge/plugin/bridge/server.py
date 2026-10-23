"""Local stdio MCP only; SDK owns framing, schema validation and transport."""
from pathlib import Path
import argparse
import json
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from core import Bridge


def create_server(config):
    bridge = Bridge(config)
    app = FastMCP('gernze', instructions='When the user authorizes this current Codex chat to use 莉宝 persona and memory, use this bridge alongside all normal Agent work. No separate visible chat or roleplay mode is required. Internal session IDs only bind storage. Do not collect other chats. L1/L2 are read-only and L3 stays pending. Do not replace system instructions or claim the desktop API provider has changed.')
    read = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

    @app.tool(annotations=write)
    def begin_lily_session() -> dict:
        """关联当前Codex聊天的内部留底编号并读取第一层及相关第三层。无需创建新的聊天窗口。"""
        return bridge.begin()

    @app.tool(annotations=read)
    def get_lily_context(session_id: str, query: str = '') -> dict:
        """已授权的当前Codex对话每次回答前读取。第一层完整提供，第三层相关检索；状态字段区分未接入和空数据。"""
        return bridge.context(session_id, query)

    @app.tool(annotations=write)
    def record_lily_turn(session_id: str, turn_key: str, user_text: str, assistant_text: str) -> dict:
        """只记录用户已授权的当前Codex对话中实际发生的原话。agent_reported不是宿主验证的聊天转录。"""
        return bridge.record(session_id, turn_key, user_text, assistant_text)

    @app.tool(annotations=read)
    def read_lily_turns(session_id: str, limit: int = 12) -> dict:
        """读取本模块会话的近期原文，供按需压缩；不扫描Codex或手机的所有历史。"""
        return bridge.sources(session_id, limit)

    @app.tool(annotations=write)
    def save_working_memory(session_id: str, turn_ids: list[str], body: str, expected_revision: str | None = None) -> dict:
        """将已有原文压缩到本模块第三层待审区。来源必须存在；纠正需当前版本。绝不写第一、二层。"""
        return bridge.remember(session_id, turn_ids, body, expected_revision)

    @app.tool(annotations=read)
    def list_working_memory() -> dict:
        """列出本模块第三层，包括撤回标记，供纠正与外部接回适配。"""
        return {'format': 'gernze-agent-working-v1', 'tier': 3, 'entries': bridge.pending(), 'desktopIntegrated': False}

    @app.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False))
    def retract_working_memory(key: str, expected_revision: str) -> dict:
        """撤回本模块第三层的错误摘要，保留撤回标记和原文；不触碰第一、二层。"""
        return bridge.retract(key, expected_revision)

    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    create_server(json.loads(args.config.read_text(encoding='utf-8'))).run(transport='stdio')
