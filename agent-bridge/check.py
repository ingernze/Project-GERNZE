from pathlib import Path
from tempfile import TemporaryDirectory
import asyncio
import json
import sqlite3
import sys
from core import Bridge, read_agent_working
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def checks():
    results = []
    def check(v, label):
        if not v:
            raise AssertionError(label)
        results.append(label)

    with TemporaryDirectory(prefix='synthetic-', dir=Path(__file__).resolve().parent) as folder:
        p = Path(folder)
        persona = p/'persona.txt';persona.write_text('合成角色：温和、不恭维。', encoding='utf-8')
        foundation = p/'foundation.json';foundation.write_text(json.dumps({'schemaVersion':1,'entries':[{'key':'synthetic','body':'合成基础'}]}), encoding='utf-8')
        desktop = p/'desktop.sqlite3'
        with sqlite3.connect(desktop) as db:
            db.executescript("CREATE TABLE lc_meta(key TEXT PRIMARY KEY,value TEXT);INSERT INTO lc_meta VALUES('owner','desktop-active'),('epoch','2');CREATE TABLE lc_sessions(id TEXT PRIMARY KEY,deleted INTEGER);INSERT INTO lc_sessions VALUES('desktop-session',0);CREATE TABLE lc_summaries(id TEXT,session_id TEXT,version INTEGER,epoch INTEGER,source_ids TEXT,text TEXT,created_at TEXT);INSERT INTO lc_summaries VALUES('old-summary','desktop-session',1,1,'[]','失效摘要','2026-10-18');INSERT INTO lc_summaries VALUES('current-summary','desktop-session',2,2,'[]','当前摘要','2026-10-19');")
        db.close()
        config = {'state_db':str(p/'agent.sqlite3'),'persona':str(persona),'foundation':str(foundation),'desktop_journal':str(desktop)}
        frozen = (persona.read_bytes(),foundation.read_bytes(),desktop.read_bytes())
        bridge = Bridge(config);a = bridge.begin()['sessionId'];b = bridge.begin()['sessionId']
        check(a != b, '并行角色会话独立')
        ctx = bridge.context(a)
        check(ctx['tier1']['foundation'][0]['body']=='合成基础' and ctx['tier1']['readOnly'], '必需第一层按需读取')
        check([r['body'] for r in ctx['tier3']]==['当前摘要'], '只读桌面摘要排除失效epoch')
        check(ctx['tier2Status']=='awaiting_desktop_layer_adapter' and not ctx['desktopConsumesAgentTier3'], '未接通状态明确，不冒充共享完成')
        turn = bridge.record(a,'turn-1','合成用户：本周先做原型。','合成助手：先保留原型。')
        check(bridge.record(a,'turn-1','合成用户：本周先做原型。','合成助手：先保留原型。')['alreadySaved'], '重复留底幂等')
        try:bridge.record(a,'turn-1','被改掉的原话','新回复')
        except ValueError:pass
        else:raise AssertionError('轮次冲突未拒绝')
        check(len(bridge.sources(a)['turns'])==1, '冲突留底不覆盖原文')
        try:bridge.remember(b,[turn['turnId']],'跨会话摘要')
        except ValueError:pass
        else:raise AssertionError('跨会话来源未拒绝')
        check(not bridge.pending(), '跨会话来源拒绝且不产生候选')
        first = bridge.remember(a,[turn['turnId']],'用户本周计划先做原型。')
        check(first['tier']==3 and not first['approved'], '摘要只进入第三层待审')
        check(bridge.remember(a,[turn['turnId']],first['body'])['alreadySaved'], '重复摘要幂等')
        newer = bridge.remember(a,[turn['turnId']],'用户说的是本周计划，并非已经完成。',first['revision'])
        try:bridge.remember(a,[turn['turnId']],'旧内容重放',first['revision'])
        except ValueError:pass
        else:raise AssertionError('旧版本未拒绝')
        check(bridge.pending()[0]['revision']==newer['revision'], '旧版本不会覆盖新纠正')
        bridge.retract(newer['key'],newer['revision'])
        try:bridge.remember(a,[turn['turnId']],first['body'])
        except ValueError:pass
        else:raise AssertionError('撤回被重放复活')
        check(bridge.pending()[0]['deleted'] and len(bridge.sources(a)['turns'])==1, '撤回防复活且保留原文')
        check(read_agent_working(p/'agent.sqlite3')['entries'][0]['deleted'], '桌面只读适配保留撤回标记')
        snapshot=p/'approved.json';snapshot.write_text(json.dumps({'format':'gernze-approved-snapshot-v1','tier':2,'entries':[]}),encoding='utf-8')
        approved_bridge=Bridge({**config,'approved_snapshot':str(snapshot)})
        check(approved_bridge.context(a)['tier2Status']=='read-only', '已接空第二层与尚未接入明确区分')
        snapshot.write_text(json.dumps({'format':'gernze-approved-snapshot-v1','tier':2,'entries':[{'key':'approved-synthetic','revision':'rev-approved','body':'已审合成资料','deleted':False}]}),encoding='utf-8')
        check(approved_bridge.context(a)['tier2'][0]['body']=='已审合成资料', '只读第二层快照接入')
        other = Bridge(config)
        other.record(b,'turn-b','第二个会话原话','另一个会话回复')
        check(len(bridge.sources(a)['turns'])==1 and len(other.sources(b)['turns'])==1, '两实例使用不抢占或串话')
        check((persona.read_bytes(),foundation.read_bytes(),desktop.read_bytes())==frozen, '核心及旧桌面库逐字节保持，未接管owner')
        cfg = p/'settings.json';cfg.write_text(json.dumps(config),encoding='utf-8')
        params = StdioServerParameters(command=sys.executable,args=[str(Path(__file__).with_name('server.py')),'--config',str(cfg)])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read,write) as client:
                await client.initialize()
                tools = (await client.list_tools()).tools
                names = {t.name for t in tools}
                check(len(names)==7 and not any('approve' in n or 'core_write' in n for n in names), '真实MCP握手与工具列表，无一二层写接口')
                result = await client.call_tool('get_lily_context',{'session_id':a,'query':'原型'})
                value=result.structuredContent or json.loads(result.content[0].text)
                check(not result.isError and value['tier1']['readOnly'], '真实stdio读取上下文')
                result = await client.call_tool('record_lily_turn',{'session_id':a,'turn_key':'turn-mcp','user_text':'合成MCP原话','assistant_text':'合成MCP回复'})
                check(not result.isError and len(bridge.sources(a)['turns'])==2, '真实stdio调用可靠留底')
                result = await client.call_tool('save_working_memory',{'session_id':a,'turn_ids':['made-up'],'body':'无来源记忆'})
                check(result.isError, '真实MCP拒绝伪造来源')
        foundation.unlink()
        try:bridge.begin()
        except FileNotFoundError:pass
        else:raise AssertionError('缺第一层仍启动')
        check(True, '缺必需第一层时明确失败')
    print(json.dumps({'passed':len(results),'checks':results,'realMCP':True,'realModel':False,'realPrivateMemoryWritten':False},ensure_ascii=False))


if __name__=='__main__':asyncio.run(checks())
