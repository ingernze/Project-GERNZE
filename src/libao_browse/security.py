from __future__ import annotations
import html,ipaddress,re,threading,time
from urllib.parse import urlsplit,urlunsplit,parse_qs

class BrowseError(Exception):
    def __init__(self,code,message):
        super().__init__(message);self.code=code;self.message=message

class Cancelled(BrowseError):
    def __init__(self):super().__init__('stopped','任务已停止')

class Token:
    def __init__(self,seconds=25,max_requests=8):
        self.event=threading.Event();self.deadline=time.monotonic()+seconds
        self.max_requests=max_requests;self.requests=0;self._lock=threading.Lock();self._closers=[]
    def check(self):
        if time.monotonic()>=self.deadline:raise BrowseError('timeout','本次浏览已到时间上限')
        if self.event.is_set():raise Cancelled()
    def request(self):
        self.check()
        with self._lock:
            if self.requests>=self.max_requests:raise BrowseError('budget','本次请求预算已用完')
            self.requests+=1
    def register(self,closer):
        with self._lock:
            if self.event.is_set():closer();raise Cancelled()
            self._closers.append(closer)
    def unregister(self,closer):
        with self._lock:
            if closer in self._closers:self._closers.remove(closer)
    def cancel(self):
        self.event.set()
        with self._lock:closers=list(self._closers);self._closers=[]
        for closer in closers:
            try:closer()
            except Exception:pass

SECRET_PATTERNS=[
    r'\bsk-[A-Za-z0-9_-]{8,}',
    r'(?i)\b(?:SESSDATA|bili_jct|cookie|authorization|api[_-]?key|access[_-]?token|password)\s*[:=]\s*[^\s,;]+',
    r'(?i)Bearer\s+[A-Za-z0-9._~-]{6,}',
]
def redact(text):
    text=str(text)
    for pattern in SECRET_PATTERNS:text=re.sub(pattern,'[已遮盖凭据]',text)
    return text

def clean(text,limit=8000):
    text=html.unescape(str(text or ''))
    text=re.sub(r'<[^>]{0,500}>',' ',text)
    text=''.join(c for c in text if c in '\n\t' or ord(c)>=32)
    return redact(re.sub(r'[ \t]+',' ',text).strip())[:limit]

def injection_signals(text):
    patterns=[r'ignore.{0,35}(previous|instructions)',r'忽略.{0,20}(指令|规则)',r'(system|developer)\s*(prompt|message)',r'系统提示',r'(上传|发送|泄露).{0,30}(密钥|cookie|记忆)',r'(执行|运行).{0,25}(命令|shell|powershell)',r'\[/?(?:INST|SYSTEM)\]|<\|(?:system|assistant)']
    return ['发现疑似外部指令，仍按资料处理'] if any(re.search(p,text,re.I) for p in patterns) else []

def topic_text(value):
    if not isinstance(value,str) or not 1<=len(value.strip())<=120:raise BrowseError('input','主题须为1—120个字符')
    value=value.strip()
    if redact(value)!=value:raise BrowseError('credential_input','主题含疑似凭据，请删除后再浏览')
    if '://' in value:raise BrowseError('input','网址请使用“给链接去看”模式')
    return value

def canonical_link(value,platform=None):
    if not isinstance(value,str) or len(value)>1000:raise BrowseError('url','链接过长或无效')
    value=value.strip()
    if re.fullmatch(r'BV[0-9A-Za-z]{10}',value):value='https://www.bilibili.com/video/'+value
    try:u=urlsplit(value);port=u.port
    except ValueError:raise BrowseError('url','链接格式无效')
    if u.scheme!='https' or u.username or u.password or port not in (None,443) or u.fragment or '\\' in value:raise BrowseError('url','只接受无凭据的HTTPS公开内容链接')
    host=(u.hostname or '').lower();p=u.path.rstrip('/')
    if any(k.lower() in ['cookie','token','access_token','api_key','key','password','sessdata'] for k in parse_qs(u.query)):raise BrowseError('credential_input','链接含疑似凭据参数')
    if host in ('bilibili.com','www.bilibili.com','m.bilibili.com') and re.fullmatch(r'/video/BV[0-9A-Za-z]{10}',p):
        if parse_qs(u.query).get('p',['1'])!=['1']:raise BrowseError('unsupported_part','首版只读P1元资料，不自动展开其他分P')
        result=('bilibili',urlunsplit(('https','www.bilibili.com',p,'','')))
    elif host=='tieba.baidu.com' and re.fullmatch(r'/p/[0-9]{5,20}',p):
        if parse_qs(u.query).get('pn',['1'])!=['1']:raise BrowseError('unsupported_page','首版只读取帖子第一页')
        result=('tieba',urlunsplit(('https',host,p,'','')))
    elif host in ('www.xiaoheihe.cn','xiaoheihe.cn') and re.fullmatch(r'/app/bbs/link/[0-9]{5,24}',p):result=('heybox',urlunsplit(('https','www.xiaoheihe.cn',p,'','')))
    elif host=='b23.tv':raise BrowseError('shortlink','首版不跟随短链，请在平台打开后复制完整视频链接')
    else:raise BrowseError('unsupported_url','只接受B站视频、贴吧帖子及小黑盒公开分享链接；不读取任意网址')
    if platform and result[0]!=platform:raise BrowseError('platform_mismatch','链接与所选平台不一致')
    return result

def public_address(address):
    try:ip=ipaddress.ip_address(address)
    except ValueError:return False
    if not ip.is_global or ip.is_multicast or ip.is_reserved:return False
    mapped=getattr(ip,'ipv4_mapped',None)
    return mapped is None or (mapped.is_global and not mapped.is_multicast and not mapped.is_reserved)

def assert_read_target(url,allow_public_text=False):
    u=urlsplit(url)
    if u.scheme!='https' or u.username or u.password or u.port not in (None,443) or u.fragment:raise BrowseError('egress_denied','网络目标不在只读白名单')
    allowed=(u.hostname=='api.bilibili.com' and u.path in ['/x/web-interface/view','/x/web-interface/popular','/x/web-interface/search/all/v2','/x/player/wbi/v2','/x/player/playurl']) or (u.hostname=='tieba.baidu.com' and bool(re.fullmatch(r'/p/\d{5,20}',u.path)))
    if u.hostname in ('aisubtitle.hdslb.com','i0.hdslb.com'):
        from .evidence import subtitle_target
        subtitle_target(url);allowed=True
    if allow_public_text and u.hostname=='en.wikipedia.org' and u.path=='/w/api.php':
        from .public_text import assert_text_target
        try:assert_text_target(url)
        except ValueError:raise BrowseError('egress_denied','文字请求参数无法解析')
        allowed=True
    if not allowed:raise BrowseError('egress_denied','目标路径不在只读白名单；写接口、任意文件和命令均不可用')
    return u
