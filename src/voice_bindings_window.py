"""Per-scene approved recording choices; explicit saves, no synthesis or autoplay."""
import tkinter as tk
from tkinter import ttk
from hecate_ui import BG,PANEL,INK,MUTED,ACCENT,ACCENT_INK,BORDER,FOCUS,PREFIX,font,label,Button,header,configure_window
from scene_voice import TRIGGER_LABELS,fixed_voice_rows

EVENT_NAMES={'workbench':'工作台首次入场','reading_start':'开始看书','reading_click':'看书点击回应','sleep':'抱帽入睡','wake_morning':'醒来 · 上午','wake_afternoon':'醒来 · 下午','wake_evening':'醒来 · 晚上','drag':'开始拖拽','slide':'松手滑行'}

def open_voice_bindings_window(pet):
    if pet.closing:return
    w=getattr(pet,'voice_bindings_window',None)
    if w is not None and w.winfo_exists():w.deiconify();w.lift();return w
    w=tk.Toplevel(pet.root);pet.voice_bindings_window=w
    configure_window(w,'赫宝 · 固定语音触发设置',780,700,(620,600))
    header(w,'场景与语音','点击录音可多选；多选时随机播放，不选则不播放。保存后生效。')
    panel=tk.Frame(w,bg=BG);panel.pack(fill='both',expand=True,padx=22,pady=(0,18))
    event_keys=list(EVENT_NAMES);event=tk.StringVar(w,EVENT_NAMES[event_keys[0]])
    combo=ttk.Combobox(panel,textvariable=event,values=list(EVENT_NAMES.values()),state='readonly',style=PREFIX+'TCombobox',font=font(w,12))
    combo.pack(fill='x',pady=(0,10));w.event_combo=combo;w.event_var=event
    detail=tk.StringVar(w);label(panel,textvariable=detail,size=12,color=MUTED,wraplength=720).pack(fill='x',pady=(0,10))
    area=tk.Frame(panel,bg=PANEL,highlightbackground=BORDER,highlightthickness=1);area.pack(fill='both',expand=True)
    rows=sorted(fixed_voice_rows(pet.voice),key=lambda r:r['id']!='WB_OPEN_01');ids=[r['id'] for r in rows]
    box=tk.Listbox(area,selectmode='multiple',exportselection=False,activestyle='dotbox',bg=PANEL,fg=INK,selectbackground=ACCENT,selectforeground=ACCENT_INK,font=font(w,12),bd=0,highlightthickness=1,highlightbackground=BORDER,highlightcolor=FOCUS)
    scroll=ttk.Scrollbar(area,command=box.yview,style=PREFIX+'Vertical.TScrollbar');scroll.pack(side='right',fill='y')
    box.configure(yscrollcommand=scroll.set);box.pack(fill='both',expand=True,padx=8,pady=8);w.clip_list=box;w.clip_ids=ids
    for r in rows:box.insert('end',f"{r['scene']} · {r['text']}  ({r['seconds']:.2f} 秒)")
    current=[event_keys[0]];drafts={};loading=[False]
    status=tk.StringVar(w,'多选结果只保存在本窗口草稿；点保存才会改变实际触发。');w.binding_status=status
    selection_note=tk.StringVar(w);label(panel,textvariable=selection_note,size=11,color=MUTED,wraplength=720).pack(fill='x',pady=(8,4))
    label(panel,textvariable=status,size=12,color=INK,wraplength=720).pack(fill='x',pady=(4,10))
    def selected_ids():return [ids[i] for i in box.curselection()]
    def remember():drafts[current[0]]=selected_ids()
    def refresh():
        loading[0]=True;key=current[0]
        values=drafts.get(key,pet.voice.events.get(key,[]))
        box.selection_clear(0,'end')
        for i,identity in enumerate(ids):
            if identity in values:box.selection_set(i)
        binding='自选设置' if key in pet.voice.binding_overrides else '默认设置'
        detail.set(TRIGGER_LABELS[key]+'。当前：'+binding+('。第二套美术暂缺此动作，设置保留供动作可用时使用。' if pet.character_style=='style2' and key.startswith(('reading','sleep','wake')) else ''))
        selection_note.set(f'已选 {len(values)} 句。工作台入场仍只触发一次；较长语音可能晚于4秒动画结束。')
        loading[0]=False
    def changed(_=None):
        if loading[0]:return
        remember();selection_note.set(f'已选 {len(selected_ids())} 句。未选任何录音时，这个场景不会播放声音。')
        status.set('本场景有未保存的选择；切换场景会保留草稿，关闭窗口不会保存草稿。')
    def switch(_=None):
        remember();current[0]=event_keys[combo.current()];refresh()
        status.set('已切换场景。选择录音后，点保存才生效。')
    def commit(mode='save'):
        key=current[0];bindings={k:list(v) for k,v in pet.voice.binding_overrides.items()}
        if mode=='default':bindings.pop(key,None)
        else:bindings[key]=[] if mode=='off' else selected_ids()
        try:pet.save_voice_bindings(bindings)
        except (OSError,ValueError) as exc:
            status.set('保存失败，原设置仍然有效：'+str(exc));return False
        drafts.pop(key,None);refresh()
        status.set('本场景已恢复默认。' if mode=='default' else '本场景已关闭声音；其他场景不变。' if not bindings[key] else '已保存，下次触发时按所选录音播放。')
        return True
    def preview():
        if not ids:return
        index=box.index('active');identity=ids[index]
        ok=pet.voice_module.play_fixed(identity)
        status.set('正在试听：'+rows[index]['text'] if ok else '无法试听，请取消静音并显示赫宝。')
    controls=tk.Frame(panel,bg=BG);controls.pack(fill='x')
    w.save_binding_button=Button(controls,text='保存这个场景',primary=True,command=commit);w.save_binding_button.pack(side='left',padx=(0,8))
    w.disable_binding_button=Button(controls,text='关闭本场景声音',command=lambda:commit('off'));w.disable_binding_button.pack(side='left')
    w.restore_binding_button=Button(controls,text='恢复本场景默认',command=lambda:commit('default'));w.restore_binding_button.pack(side='right')
    playback=tk.Frame(panel,bg=BG);playback.pack(fill='x',pady=(10,0))
    Button(playback,text='试听光标所在录音',command=preview).pack(side='left')
    Button(playback,text='停止试听',command=lambda:pet.voice.stop('preview')).pack(side='left',padx=8)
    combo.bind('<<ComboboxSelected>>',switch);box.bind('<<ListboxSelect>>',changed)
    box.bind('<Return>',lambda _:(preview(),'break')[1]);w.bind('<Control-s>',lambda _:(commit(),'break')[1])
    def close():
        pet.voice.stop('preview');pet.voice_bindings_window=None;w.destroy()
    w.close=close;w.protocol('WM_DELETE_WINDOW',close);w.bind('<Escape>',lambda _:close());refresh()
    return w
