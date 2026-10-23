"""Frozen release contract and bounded transport inputs (no type coercion)."""
import base64
import hashlib
import ipaddress
import json
import re
import time
import uuid

MAX_APK=536870912
MAX_JSON=16384
HEX=re.compile(r'[0-9a-f]{64}\Z')
TOKEN=re.compile(r'[A-Za-z0-9_-]{43}\Z')
RELEASE_KEYS={'schemaVersion','artifactId','packageName','versionCode','versionName',
              'size','sha256','signerCertificateSha256','minSdkVersion'}
PAIR_KEYS={'protocol','serverId','host','port','certificateDer','certificateSha256','pairingSecret','expiresAt'}
TLS_NAME='hebao.local'

class Error(ValueError):
    def __init__(self,code='invalid_input'):
        self.code=code
        super().__init__(code)

def require(ok,code='invalid_input'):
    if not ok:raise Error(code)

def uid(v):
    require(type(v) is str)
    try:require(str(uuid.UUID(v))==v)
    except (ValueError,AttributeError):raise Error('invalid_input') from None
    return v

def private_host(v):
    require(type(v) is str)
    try:a=ipaddress.IPv4Address(v)
    except ipaddress.AddressValueError:raise Error() from None
    require(str(a)==v and any(a in ipaddress.ip_network(n) for n in
                             ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')))
    return v

def integer(v,lo,hi):require(type(v) is int and lo<=v<=hi)
def string(v,n):
    require(type(v) is str and 0<len(v)<=n and v==v.strip() and
            not any(ord(c)<32 or 0xD800<=ord(c)<=0xDFFF for c in v))

def release(v):
    require(type(v) is dict and set(v)==RELEASE_KEYS)
    require(type(v['schemaVersion']) is int and v['schemaVersion']==1)
    uid(v['artifactId']);integer(v['size'],1,MAX_APK);integer(v['versionCode'],1,9007199254740991)
    integer(v['minSdkVersion'],1,2147483647)
    string(v['versionName'],64)
    require(type(v['packageName']) is str and len(v['packageName'])<=255 and
            re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+',v['packageName']))
    require(type(v['sha256']) is str and HEX.fullmatch(v['sha256']))
    signers=v['signerCertificateSha256']
    require(type(signers) is list and len(signers)>=1)
    require(all(type(s) is str and HEX.fullmatch(s) for s in signers))
    require(signers==sorted(set(signers)))
    return v

def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def pairs(items):
    d={}
    for k,v in items:
        require(k not in d);d[k]=v
    return d
def parse(data,limit=MAX_JSON):
    try:
        if type(data) is str:data=data.encode('utf-8')
        require(type(data) is bytes and len(data)<=limit)
        return json.loads(data.decode('utf-8'),object_pairs_hook=pairs,
                          parse_constant=lambda _:require(False))
    except (UnicodeError,ValueError,RecursionError):raise Error() from None

def pairing(v,*,check_expiry=True):
    require(type(v) is dict and set(v)==PAIR_KEYS and v['protocol']=='hebao-pair-v1')
    uid(v['serverId']);private_host(v['host']);integer(v['port'],1024,65535)
    integer(v['expiresAt'],1,9007199254740991)
    if check_expiry:require(0<v['expiresAt']-int(time.time()*1000)<=300000,'pairing_expired')
    require(type(v['pairingSecret']) is str and TOKEN.fullmatch(v['pairingSecret']))
    require(type(v['certificateSha256']) is str and HEX.fullmatch(v['certificateSha256']))
    require(type(v['certificateDer']) is str and len(v['certificateDer'])<=4096)
    try:der=base64.b64decode(v['certificateDer'],validate=True)
    except ValueError:raise Error() from None
    require(base64.b64encode(der).decode()==v['certificateDer'] and 128<=len(der)<=3072)
    require(hashlib.sha256(der).hexdigest()==v['certificateSha256'],'tls_mismatch')
    return v
