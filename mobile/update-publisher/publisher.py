"""Single immutable APK publisher. Python 3.12; TLS 1.2+, no HTTP fallback."""
import argparse
import base64
import csv
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import hashlib
from http.server import BaseHTTPRequestHandler,HTTPServer
import os
from pathlib import Path
import re
import secrets
import signal
import socketserver
import sqlite3
import ssl
import stat
import subprocess
import threading
import time
import uuid

from event_outbox import AuthenticatedPeer, EventError
from codex_tasks import CodexTasks
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID,NameOID
from rules import (Error,MAX_APK,TLS_NAME,TOKEN,canonical,integer,parse,private_host,
                   release,require,uid)


def private_directory(path):
    path=Path(path).absolute()
    require(not path.is_symlink(),'private_storage_failed')
    require(path.parent!=path and path!=Path.home().absolute(),'private_storage_failed')
    marker=path/'.hebao-publisher-private-v1'
    existed=path.exists()
    if existed:require(marker.is_file() and not marker.is_symlink(),'private_storage_failed')
    path.mkdir(mode=0o700,parents=True,exist_ok=True)
    require(path.is_dir() and path.resolve()==path,'private_storage_failed')
    if os.name=='nt':
        try:
            raw=subprocess.check_output(['whoami','/user','/fo','csv','/nh'],text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            sid=list(csv.reader(raw.strip().splitlines()))[0][1]
            require(re.fullmatch(r'S-1-[0-9-]+',sid),'private_storage_failed')
            # Replace this dedicated application's DACL, not a shared ancestor
            # or global setting. Existing explicit broad grants are removed.
            import ctypes
            from ctypes import wintypes
            adv=ctypes.WinDLL('advapi32',use_last_error=True)
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            descriptor=ctypes.c_void_p()
            convert=adv.ConvertStringSecurityDescriptorToSecurityDescriptorW
            convert.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,ctypes.POINTER(ctypes.c_void_p),ctypes.c_void_p]
            convert.restype=wintypes.BOOL
            get_dacl=adv.GetSecurityDescriptorDacl
            get_dacl.argtypes=[ctypes.c_void_p,ctypes.POINTER(wintypes.BOOL),ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(wintypes.BOOL)]
            get_dacl.restype=wintypes.BOOL
            apply=adv.SetNamedSecurityInfoW
            apply.argtypes=[wintypes.LPWSTR,ctypes.c_int,wintypes.DWORD,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p]
            apply.restype=wintypes.DWORD
            kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
            require(bool(convert('D:P(A;OICI;FA;;;'+sid+')(A;OICI;FA;;;SY)',1,ctypes.byref(descriptor),None)),'private_storage_failed')
            try:
                present=wintypes.BOOL();defaulted=wintypes.BOOL();dacl=ctypes.c_void_p()
                require(bool(get_dacl(descriptor,ctypes.byref(present),ctypes.byref(dacl),ctypes.byref(defaulted))) and present.value and bool(dacl.value),'private_storage_failed')
                require(apply(ctypes.create_unicode_buffer(str(path)),1,0x80000004,None,None,dacl,None)==0,'private_storage_failed')
            finally:kernel.LocalFree(descriptor)
        except Exception:raise Error('private_storage_failed') from None
    else:
        info=path.stat()
        require(info.st_uid==os.getuid() and not info.st_mode&0o077,'private_storage_failed')
    if not existed:atomic(marker,b'hebao-publisher-private-v1\n')
    return path


class InstanceLock:
    def __init__(self,directory):
        path=directory/'.instance-lock'
        require(not path.is_symlink(),'private_storage_failed')
        self.fd=os.open(path,os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            if os.name=='nt':
                import msvcrt
                if os.fstat(self.fd).st_size==0:os.write(self.fd,b'0')
                os.lseek(self.fd,0,0);msvcrt.locking(self.fd,msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:os.close(self.fd);self.fd=None;raise Error('busy') from None
    def close(self):
        if self.fd is not None:os.close(self.fd);self.fd=None

def atomic(path,data):
    tmp=path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    try:
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)

def regular_open(path):
    require(not path.is_symlink(),'integrity_failed')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd);raise Error('integrity_failed')
    return os.fdopen(fd,'rb')

def identity(directory):
    paths=[directory/n for n in ['identity.json','certificate.pem','private-key.pem']]
    existing=[p.exists() for p in paths]
    require(not any(p.is_symlink() for p in paths),'private_storage_failed')
    if not any(existing):
        key=ec.generate_private_key(ec.SECP256R1())
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,TLS_NAME)])
        now=datetime.now(timezone.utc)
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name)
              .public_key(key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=3650))
              .add_extension(x509.SubjectAlternativeName([x509.DNSName(TLS_NAME)]),critical=False)
              .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
              .add_extension(x509.KeyUsage(True,False,False,False,False,True,False,False,False),critical=True)
              .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
              .sign(key,hashes.SHA256()))
        atomic(paths[2],key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        atomic(paths[1],cert.public_bytes(serialization.Encoding.PEM))
        atomic(paths[0],canonical({'serverId':str(uuid.uuid4())}))
    else:require(all(existing),'identity_invalid')
    server_id=parse(paths[0].read_bytes());require(set(server_id)=={'serverId'},'identity_invalid');uid(server_id['serverId'])
    cert=x509.load_pem_x509_certificate(paths[1].read_bytes())
    require(cert.not_valid_before_utc<=datetime.now(timezone.utc)<cert.not_valid_after_utc,'identity_invalid')
    require(TLS_NAME in cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName),'identity_invalid')
    der=cert.public_bytes(serialization.Encoding.DER)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version=ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(paths[1]),str(paths[2]))
    return server_id['serverId'],der,context


class Publisher:
    def __init__(self,directory,apk,manifest,host,port=0,*,memory_path=None,codex_plugin_manifest=None):
        self.directory=private_directory(directory);self.host=private_host(host)
        require(type(port) is int and (port==0 or 1024<=port<=65535))
        self.memory_path=Path(memory_path) if memory_path else None;self.memory_service=None
        self.codex_plugin_manifest=codex_plugin_manifest;self.codex_service=None;self.layer_service=None
        self.instance_lock=InstanceLock(self.directory)
        try:self.initialize(apk,manifest,host,port)
        except Exception:self.instance_lock.close();raise

    def initialize(self,apk,manifest,host,port):
        self.release_bytes=canonical(release(parse(canonical(manifest))))
        self.server_id,self.der,self.context=identity(self.directory)
        self.lock=threading.RLock();self.invitation=None;self.attempts=[]
        self.closed=False
        self.stopping=threading.Event()
        self.db_path=self.directory/'authorizations.sqlite3'
        require(not self.db_path.is_symlink(),'private_storage_failed')
        with self.database() as db:
            db.execute('CREATE TABLE IF NOT EXISTS authorizations (pairing_id TEXT PRIMARY KEY,device_id TEXT NOT NULL,token_hash TEXT NOT NULL,revoked INTEGER NOT NULL)')
        if os.name!='nt':os.chmod(self.db_path,0o600)
        self.snapshot=self.freeze(Path(apk))
        # Use descriptor metadata on both sides; Windows path stat and fstat
        # can disagree on ctime even for an unchanged, correctly hashed file.
        with regular_open(self.snapshot) as frozen:
            self.signature=self.file_signature(os.fstat(frozen.fileno()))
        self.server=TLSHTTPServer((host,port),Handler,self)
        self.port=self.server.server_port
        require(self.port>=1024)
        self.thread=None

    @contextmanager
    def database(self):
        connection=sqlite3.connect(self.db_path,timeout=5)
        try:
            with connection:yield connection
        finally:connection.close()

    @property
    def release(self):
        # Return a detached view; changing a caller's dict cannot republish.
        return parse(self.release_bytes)

    @staticmethod
    def file_signature(s):return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns

    def freeze(self,apk):
        folder=private_directory(self.directory/'releases')
        dest=folder/(self.release['artifactId']+'.apk')
        metadata=folder/(self.release['artifactId']+'.json')
        if dest.exists() or metadata.exists():
            require(dest.exists() and metadata.exists() and not metadata.is_symlink() and metadata.read_bytes()==self.release_bytes,'artifact_collision')
            with regular_open(dest) as f:
                require(os.fstat(f.fileno()).st_size==self.release['size'] and hashlib.file_digest(f,'sha256').hexdigest()==self.release['sha256'],'integrity_failed')
            return dest
        temp=folder/(self.release['artifactId']+'.part')
        try:
            with regular_open(apk) as source:
                before=self.file_signature(os.fstat(source.fileno()))
                require(before[2]==self.release['size'],'integrity_failed')
                fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                size=0;digest=hashlib.sha256()
                with os.fdopen(fd,'wb') as target:
                    while block:=source.read(65536):
                        size+=len(block);require(size<=self.release['size'] and size<=MAX_APK,'integrity_failed')
                        target.write(block);digest.update(block)
                    target.flush();os.fsync(target.fileno())
                require(size==self.release['size'] and digest.hexdigest()==self.release['sha256'] and before==self.file_signature(os.fstat(source.fileno())),'integrity_failed')
            os.replace(temp,dest);atomic(metadata,self.release_bytes)
        finally:temp.unlink(missing_ok=True)
        return dest

    def issue_invitation(self,seconds=180):
        integer(seconds,1,300)
        secret=secrets.token_urlsafe(32)
        with self.lock:
            self.invitation={'hash':hashlib.sha256(secret.encode()).hexdigest(),'deadline':time.monotonic()+seconds,'used':False}
            payload={'protocol':'hebao-pair-v1','serverId':self.server_id,'host':self.host,'port':self.port,
                     'certificateDer':base64.b64encode(self.der).decode(),'certificateSha256':hashlib.sha256(self.der).hexdigest(),
                     'pairingSecret':secret,'expiresAt':int(time.time()*1000)+seconds*1000}
            atomic(self.directory/'pairing.json',canonical(payload))
            return payload

    def memories(self):
        require(self.memory_path is not None,'memory_unavailable')
        with self.lock:
            if self.memory_service is None:
                from memory_service import MemoryService
                self.memory_service=MemoryService(self.memory_path,self.server_id)
            return self.memory_service

    def layers(self):
        require(self.memory_path is not None,'memory_unavailable')
        with self.lock:
            if self.layer_service is None:
                from layer_service import LayerService
                self.layer_service=LayerService(self.memory_path.with_name('chat-sessions.sqlite3'),self.server_id)
            return self.layer_service

    def codex_tasks(self):
        with self.lock:
            if self.codex_service is None:
                self.codex_service=CodexTasks(self.directory,self.codex_plugin_manifest,self.server_id)
            return self.codex_service

    def pair(self,body):
        require(type(body) is dict and set(body)=={'deviceId','pairingSecret','serverId'})
        uid(body['deviceId']);uid(body['serverId'])
        require(type(body['pairingSecret']) is str and TOKEN.fullmatch(body['pairingSecret']))
        with self.lock:
            now=time.monotonic();self.attempts=[t for t in self.attempts if now-t<60]
            require(len(self.attempts)<12,'busy');self.attempts.append(now)
            i=self.invitation
            require(i is not None and body['serverId']==self.server_id,'authentication_failed')
            require(secrets.compare_digest(i['hash'],hashlib.sha256(body['pairingSecret'].encode()).hexdigest()),'authentication_failed')
            require(not i['used'],'pairing_replayed');require(now<i['deadline'],'pairing_expired')
            token=secrets.token_urlsafe(32);pair_id=str(uuid.uuid4())
            with self.database() as db:
                require(db.execute('SELECT count(*) FROM authorizations WHERE revoked=0 AND device_id<>?',(body['deviceId'],)).fetchone()[0]<64,'busy')
                db.execute('UPDATE authorizations SET revoked=1 WHERE device_id=?',(body['deviceId'],))
                db.execute('INSERT INTO authorizations VALUES (?,?,?,0)',(pair_id,body['deviceId'],hashlib.sha256(token.encode()).hexdigest()))
            i['used']=True;(self.directory/'pairing.json').unlink(missing_ok=True)
            return {'pairingId':pair_id,'token':token,'serverId':self.server_id}

    def authorized(self,pair_id,token):
        try:
            uid(pair_id)
            if type(token) is not str or not TOKEN.fullmatch(token):return False
            with self.lock,self.database() as db:
                row=db.execute('SELECT token_hash,revoked FROM authorizations WHERE pairing_id=?',(pair_id,)).fetchone()
                return bool(row and not row[1] and secrets.compare_digest(row[0],hashlib.sha256(token.encode()).hexdigest()))
        except Error:return False

    def revoke(self,pair_id):
        uid(pair_id)
        with self.lock,self.database() as db:db.execute('UPDATE authorizations SET revoked=1 WHERE pairing_id=?',(pair_id,))
        if self.codex_service is not None:self.codex_service.revoke(pair_id)

    def start(self):
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.05},daemon=True)
        self.thread.start();return self

    def close(self):
        with self.lock:
            if self.closed:return
            self.closed=True
        self.stopping.set()
        if self.thread:self.server.shutdown();self.thread.join(5)
        self.server.server_close();(self.directory/'pairing.json').unlink(missing_ok=True)
        self.instance_lock.close()


class TLSHTTPServer(socketserver.ThreadingMixIn,HTTPServer):
    daemon_threads=True
    allow_reuse_address=True
    def __init__(self,address,handler,publisher):
        self.publisher=publisher;self.slots=threading.BoundedSemaphore(8)
        super().__init__(address,handler)
    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):request.close();return
        try:super().process_request(request,address)
        except Exception:self.slots.release();raise
    def process_request_thread(self,request,address):
        try:
            request.settimeout(10)
            with self.publisher.context.wrap_socket(request,server_side=True) as secured:
                self.finish_request(secured,address)
        except (OSError,Error):pass
        finally:request.close();self.slots.release()
    def handle_error(self,*_):pass  # Do not log request lines, tokens or private paths.


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    server_version='HebaoPublisher/1'
    sys_version=''
    def log_message(self,*_):pass
    def send_error(self,*_):self.reply(400,{'code':'invalid_input'})
    def reply(self,status,value):
        data=canonical(value);self.send_response(status)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store');self.send_header('Connection','close');self.end_headers()
        self.close_connection=True;self.wfile.write(data)
    def check_headers(self,post=False):
        for k in ['Host','Authorization','X-Hebao-Pairing','Content-Length','Content-Type','Range']:
            require(len(self.headers.get_all(k,[]))<=1)
        require(self.headers.get('Host')==f'{self.server.publisher.host}:{self.server.publisher.port}')
        require(not any(self.headers.get(k) for k in ['Transfer-Encoding','Content-Encoding','Origin']))
        if not post:require(self.headers.get('Content-Length','0')=='0')
    def credentials(self):
        auth=self.headers.get('Authorization','');require(auth.startswith('Bearer '),'authentication_failed')
        pair_id=self.headers.get('X-Hebao-Pairing','');token=auth[7:]
        require(self.server.publisher.authorized(pair_id,token),'authentication_failed')
        return pair_id,token
    def do_POST(self):
        try:
            self.check_headers(True)
            require(self.headers.get('Content-Type')=='application/json')
            length=self.headers.get('Content-Length','');require(re.fullmatch(r'0|[1-9][0-9]{0,7}',length) is not None)
            memory_route=self.path in ('/v1/raw/exchange','/v1/memory/exchange','/v1/memory/decide','/v1/layers/exchange','/v1/layers/decide')
            codex_route=self.path in ('/v1/codex/subscription','/v1/codex/events','/v1/codex/ack')
            codex_peer=None
            if memory_route:pair_id,_=self.credentials()
            if codex_route:codex_peer=AuthenticatedPeer(self.credentials()[0])
            limit=524288 if self.path=='/v1/raw/exchange' else 8388608 if memory_route else 4096
            n=int(length);require(0<n<=limit)
            body=self.rfile.read(n);require(len(body)==n)
            body=parse(body,limit)
            if codex_route:self.reply(200,self.server.publisher.codex_tasks().dispatch(self.path,body,codex_peer))
            elif self.path=='/v1/pair':self.reply(200,self.server.publisher.pair(body))
            elif self.path=='/v1/unpair':
                pair_id,_=self.credentials();require(body=={})
                self.server.publisher.revoke(pair_id);self.reply(200,{'status':'unpaired'})
            elif self.path in ('/v1/raw/exchange','/v1/layers/exchange'):
                p=self.server.publisher
                with p.database() as db:device=db.execute('SELECT device_id FROM authorizations WHERE pairing_id=? AND revoked=0',(pair_id,)).fetchone()[0]
                if self.path=='/v1/raw/exchange':
                    require(p.memory_path is not None,'memory_unavailable')
                    from layer_service import PhoneArchive
                    result=PhoneArchive(p.memory_path.with_name('chat-sessions.sqlite3')).exchange(device,body);result['serverId']=p.server_id
                else:result=p.layers().exchange(body,peer_device=device)
                self.reply(200,result)
            elif self.path=='/v1/layers/decide':self.reply(200,self.server.publisher.layers().decide(body))
            elif self.path=='/v1/memory/exchange':self.reply(200,self.server.publisher.memories().exchange(body))
            elif self.path=='/v1/memory/decide':self.reply(200,self.server.publisher.memories().decide(body))
            else:self.reply(404,{'code':'invalid_input'})
        except (Error,EventError) as e:self.reply(401 if e.code.startswith(('authentication','pairing_')) else 400,{'code':e.code})
        except (ValueError,OSError):self.reply(409,{'code':'memory_failed'})
    def do_GET(self):
        try:
            self.check_headers();pair_id,token=self.credentials()
            p=self.server.publisher
            if self.headers.get('Range') is not None:self.reply(416,{'code':'range_not_supported'});return
            if self.path=='/v1/codex/info':self.reply(200,p.codex_tasks().dispatch(self.path,None,AuthenticatedPeer(pair_id)));return
            if self.path=='/v1/release':self.reply(200,p.release);return
            if self.path=='/v1/layers/info':self.reply(200,p.layers().info());return
            if self.path=='/v1/memory/info':self.reply(200,p.memories().info());return
            if self.path!='/v1/artifacts/'+p.release['artifactId']:
                self.reply(404,{'code':'invalid_input'});return
            with regular_open(p.snapshot) as f:
                require(p.file_signature(os.fstat(f.fileno()))==p.signature,'integrity_failed')
                require(hashlib.file_digest(f,'sha256').hexdigest()==p.release['sha256'],'integrity_failed');f.seek(0)
                self.send_response(200);self.send_header('Content-Type','application/vnd.android.package-archive')
                self.send_header('Content-Length',str(p.release['size']));self.send_header('ETag','"'+p.release['sha256']+'"')
                self.send_header('Connection','close');self.send_header('Cache-Control','no-store');self.end_headers();self.close_connection=True
                while block:=f.read(65536):
                    if p.stopping.is_set() or not p.authorized(pair_id,token) or p.file_signature(os.fstat(f.fileno()))!=p.signature:return
                    self.wfile.write(block)
        except (Error,EventError) as e:self.reply(401 if e.code=='authentication_failed' else 409,{'code':e.code})
        except (ValueError,OSError):self.reply(409,{'code':'memory_failed'})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-plugin-manifest',type=Path)
    parser.add_argument('--host',required=True);parser.add_argument('--port',type=int,default=53319)
    parser.add_argument('--private-dir',required=True);parser.add_argument('--apk',required=True)
    parser.add_argument('--release',required=True,help='strict ReleaseManifest JSON, not an installer sidecar')
    args=parser.parse_args();publisher=None
    def stop_signal(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop_signal)
    try:
        publisher=Publisher(args.private_dir,args.apk,parse(Path(args.release).read_bytes()),args.host,args.port,codex_plugin_manifest=args.codex_plugin_manifest).start()
        publisher.issue_invitation()
        print('已启动单包 HTTPS 发布。配对载荷保存在所选私有目录的 pairing.json，180秒有效。')
        print('本机命令：pair 刷新载荷；devices 查看授权编号；revoke <pairingId> 撤销；quit 停止。不要分享载荷或目录。')
        while True:
            try:command=input().strip()
            except EOFError:break
            if command=='quit':break
            if command=='pair':publisher.issue_invitation();print('已刷新一次性载荷。')
            elif command=='devices':
                with publisher.lock,publisher.database() as db:
                    for pair_id,device_id in db.execute('SELECT pairing_id,device_id FROM authorizations WHERE revoked=0 ORDER BY pairing_id'):
                        print('pairingId='+pair_id+' deviceId='+device_id)
            elif command.startswith('revoke '):
                try:publisher.revoke(command[7:]);print('已撤销指定授权。')
                except Error:print('编号无效。')
    except KeyboardInterrupt:pass
    except (Error,OSError,ValueError):print('发布未启动或已停止，请核对私网地址、私有目录和发布文件。');return 2
    finally:
        if publisher:publisher.close()
    return 0

if __name__=='__main__':raise SystemExit(main())
