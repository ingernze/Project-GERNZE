"""Small local publisher window; no cloud, auto-start or remote installation."""
from pathlib import Path
import argparse
import ipaddress
import json
import os
import socket
import sys
import threading
import time

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'vendor'))
import qrcode
from publisher import Publisher

def addresses():
    try:
        values={row[4][0] for row in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET)}
        nets=[ipaddress.ip_network(n) for n in ['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16']]
        return sorted((s for s in values if any(ipaddress.ip_address(s) in net for net in nets)),key=lambda s:(s.endswith('.1'),not s.startswith('192.168.'),s))
    except OSError:return []

def qr_matrix(payload):
    code=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=4,border=4)
    code.add_data(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')))
    code.make(fit=True)
    return code.get_matrix()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--self-test',action='store_true');parser.add_argument('--auto-start',action='store_true');args=parser.parse_args()
    if args.self_test:
        matrix=qr_matrix({'protocol':'hebao-pair-v1','synthetic':'not-a-real-pairing-secret'})
        assert len(matrix)>20 and len(matrix)==len(matrix[0]);print('QR matrix generation passed; no publisher or camera opened.');return
    import tkinter as tk
    from tkinter import ttk
    window=tk.Tk();window.title('莉宝 · 电脑更新');window.geometry('540x720');window.minsize(490,650)
    font=('Microsoft YaHei UI',11)
    frame=ttk.Frame(window,padding=18);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='把更新交给手机里的莉宝',font=('Microsoft YaHei UI',16)).pack(anchor='w')
    ttk.Label(frame,text='电脑先连接手机热点。此窗口保持打开，手机才能下载。',font=font,wraplength=480).pack(anchor='w',pady=10)
    row=ttk.Frame(frame);row.pack(fill='x')
    ttk.Label(row,text='电脑地址',font=font).pack(side='left')
    ips=addresses();host=tk.StringVar(value=ips[0] if ips else '')
    ttk.Combobox(row,textvariable=host,values=ips,width=22).pack(side='left',padx=10)
    start=ttk.Button(row,text='开始发布');start.pack(side='right')
    status=tk.StringVar(value='读取当前更新清单…')
    ttk.Label(frame,textvariable=status,font=font,wraplength=480).pack(anchor='w',pady=10)
    canvas=tk.Canvas(frame,width=440,height=440,bg='white',highlightthickness=0);canvas.pack()
    fingerprint=tk.StringVar(value='首次配对请用手机莉宝：设置 → 电脑更新 → 扫描电脑二维码。')
    ttk.Label(frame,textvariable=fingerprint,font=('Consolas',10),wraplength=480).pack(anchor='w',pady=10)
    controls=ttk.Frame(frame);controls.pack(fill='x')
    refresh=ttk.Button(controls,text='刷新配对码',state='disabled');refresh.pack(side='left')
    stop=ttk.Button(controls,text='停止发布',state='disabled');stop.pack(side='right')
    state={'publisher':None,'working':False,'closing':False,'payload':None}
    config=None
    try:
        config=json.loads((HERE/'current-release.json').read_text(encoding='utf-8'))
        status.set('准备发布 '+config['release']['versionName']+'。点“开始发布”。')
    except Exception:status.set('没有可用更新清单，请交给主干重新生成。');start.config(state='disabled')

    def show_pair():
        p=state['publisher']
        if not p:return
        payload=p.issue_invitation();state['payload']=payload;canvas.delete('all')
        matrix=qr_matrix(payload);n=len(matrix);scale=max(1,440//n);offset=(440-scale*n)/2
        for y,line in enumerate(matrix):
            for x,black in enumerate(line):
                if black:canvas.create_rectangle(offset+x*scale,offset+y*scale,offset+(x+1)*scale,offset+(y+1)*scale,fill='black',outline='')
        fp=payload['certificateSha256'];fingerprint.set('电脑身份指纹：\n'+' '.join(fp[i:i+4] for i in range(0,len(fp),4)))
        status.set('配对码180秒内有效。配对过的手机可以直接点“检查更新”。')

    def cleanup_old(p):
        # Only our marked, locked release directory; keep one current snapshot.
        folder=p.snapshot.parent
        for file in folder.iterdir():
            if file.is_symlink() or file.suffix not in ['.apk','.json']:continue
            try:
                import uuid
                if str(uuid.UUID(file.stem))!=file.stem or file.stem==p.release['artifactId']:continue
            except ValueError:continue
            file.unlink(missing_ok=True)

    def completed(p,error):
        state['working']=False
        if state['closing']:
            if p:p.close()
            window.destroy();return
        if error:
            status.set('未能开始发布。请检查电脑地址、端口是否占用，以及本地文件权限。');start.config(state='normal');return
        state['publisher']=p;refresh.config(state='normal');stop.config(state='normal');show_pair()

    def begin():
        if state['working'] or state['publisher']:return
        state['working']=True;start.config(state='disabled');status.set('正在校验并准备更新文件…')
        selected=host.get().strip()
        def work():
            p=None;error=False
            try:
                state_root=Path(os.environ['HECATE_STATE_DIR']) if os.environ.get('HECATE_STATE_DIR') else Path(os.environ.get('LOCALAPPDATA') or Path.home())/'HecatePixelPetDeepSeekTrial'
                if not os.environ.get('HECATE_STATE_DIR') and not (state_root/'workbench/companion-memory.sqlite3').exists():state_root=HERE.parents[1]/'src'
                p=Publisher(HERE/'.state',Path(config['apkPath']),config['release'],selected,53319,memory_path=state_root/'workbench/companion-memory.sqlite3',codex_plugin_manifest=config.get('codexPluginManifest')).start();cleanup_old(p)
            except Exception:
                error=True
                if p:p.close();p=None
            window.after(0,lambda:completed(p,error))
        threading.Thread(target=work,daemon=True).start()

    def end(close=False):
        if state['working']:
            if close:state['closing']=True;status.set('正在保存并停止…')
            return
        p=state['publisher'];state['publisher']=None;state['payload']=None
        if p:p.close()
        canvas.delete('all');refresh.config(state='disabled');stop.config(state='disabled')
        if close:window.destroy()
        else:start.config(state='normal' if config else 'disabled');status.set('已停止发布。电脑身份保留，下次启动仍可连接。')

    def tick():
        p=state['publisher'];payload=state['payload']
        if p and payload:
            with p.lock:used=bool(p.invitation and p.invitation['used'])
            if used or payload['expiresAt']<=time.time()*1000:
                canvas.delete('all');canvas.create_text(220,220,text='已配对，可在手机检查更新' if used else '配对码已过期，点下方刷新',width=390,font=font,fill='#222')
                state['payload']=None
        window.after(1000,tick)
    start.config(command=begin);refresh.config(command=show_pair);stop.config(command=end)
    window.protocol('WM_DELETE_WINDOW',lambda:end(True));window.after(1000,tick);
    if args.auto_start and config:window.after(100,begin)
    window.mainloop()

if __name__=='__main__':main()
