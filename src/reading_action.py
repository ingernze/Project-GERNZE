"""Manifest-driven pixel reading resource. Runtime policy lives in the host."""
import json
from pathlib import Path
from PIL import Image


def load_reading_action(asset_dir, idle_image):
    asset_dir=Path(asset_dir).resolve()
    data=json.loads((asset_dir/'manifest.json').read_text(encoding='utf-8'))
    if data.get('renderer')!='pixel' or data.get('action')!='reading':
        raise ValueError('Unsupported reading manifest')
    canvas=data['canvas']
    if canvas!=list(idle_image.size):
        raise ValueError('Reading canvas does not match idle canvas')
    frames=[];indices={}
    entries=data['frames']
    if not isinstance(entries,list) or not 1<=len(entries)<=120:
        raise ValueError('Invalid reading frame list')
    for entry in entries:
        name=entry['file']
        if name in indices:raise ValueError('Duplicate reading frame name')
        path=(asset_dir/name).resolve()
        if not path.is_relative_to(asset_dir):raise ValueError('Reading frame escapes assets')
        with Image.open(path) as im:
            if im.size!=tuple(canvas) or im.mode!='RGBA':
                raise ValueError('Invalid reading canvas or alpha format')
            image=im.copy()
        indices[name]=len(frames)
        frames.append((image,None))
    phases={}
    for phase in ('enter','glance','exit'):
        sequence=data['phases'][phase]
        if not isinstance(sequence,list) or not 1<=len(sequence)<=120:
            raise ValueError('Empty or invalid reading phase')
        phases[phase]=[]
        for entry in sequence:
            duration=entry['duration_ms']
            if type(duration) is not int or not 30<=duration<=10000:
                raise ValueError('Invalid reading phase duration')
            phases[phase].append((indices[entry['file']],duration))
    hold=indices[data['hold_frame']]
    for index in (phases['enter'][0][0],phases['exit'][-1][0]):
        if frames[index][0].tobytes()!=idle_image.tobytes():
            raise ValueError('Reading endpoint differs from runtime idle')
    waits=data['idle_wait_ms'];durations=data['reading_duration_ms']
    for bounds in (waits,durations):
        if (not isinstance(bounds,list) or len(bounds)!=2
            or not all(type(v) is int for v in bounds)
            or not 1000<=bounds[0]<=bounds[1]<=3600000):
            raise ValueError('Invalid reading policy duration')
    return {'version':data['version'],'phases':phases,'hold_index':hold,
            'manifest':data},frames,waits,durations
