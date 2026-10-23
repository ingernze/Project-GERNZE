"""Style-local asset roots and atlas decoding; no cross-style fallbacks."""
from pathlib import Path
from PIL import Image,ImageOps

STYLE_NAMES={'style2':'第一套 · 插画（默认）','original':'第二套 · 像素（备用）'}
def style_paths(root,style):
    root=Path(root)
    if style=='original':
        return dict(idle=root/'assets/pixel/libao/idle',reading=root/'assets/pixel/libao/reading',actions=root/'assets/pixel/libao/actions',walk=root/'assets/walk',grab=root/'assets/grab')
    if style!='style2':raise ValueError('Unknown character style')
    base=root/'assets/styles/style2'
    return dict(idle=base,reading=None,actions=base/'actions',walk=base/'walk',grab=base/'grab')

def decode_atlas(source,entry,canvas):
    box=entry['atlas_box']
    if (not isinstance(box,list) or len(box)!=4 or any(type(x) is not int for x in box)
        or not 0<=box[0]<box[2]<=source.width or not 0<=box[1]<box[3]<=source.height):
        raise ValueError('Invalid sprite atlas cell')
    if source.mode!='RGBA':raise ValueError('Atlas must have real RGBA transparency')
    tile=source.crop(tuple(box))
    cutoff=entry.get('alpha_cutoff')
    if cutoff is not None:
        if type(cutoff) is not int or not 1<=cutoff<=255:raise ValueError('Invalid alpha cutoff')
        # Interpret the source alpha for the Windows color-key renderer,
        # without editing the atlas on disk or guessing transparency by RGB.
        tile.putalpha(tile.getchannel('A').point(lambda a:255 if a>=cutoff else 0))
    alpha=tile.getchannel('A')
    if alpha.getbbox() is None or alpha.getextrema()[0]>0:raise ValueError('Atlas cell must contain a transparent sprite')
    # Fixed mapping for every cell, never per-frame bounding-box recentering.
    if entry.get('fit'):
        fitted=ImageOps.contain(tile,tuple(canvas),Image.Resampling.LANCZOS)
        result=Image.new('RGBA',tuple(canvas),(0,0,0,0))
        result.paste(fitted,((canvas[0]-fitted.width)//2,canvas[1]-fitted.height))
        return result
    return tile.resize(tuple(canvas),Image.Resampling.LANCZOS)


def make_photo(image,size,resampling):
    from PIL import ImageTk
    display=image.resize(size,resampling)
    if resampling==Image.Resampling.LANCZOS:
        # Tk on Windows uses a color key, not a layered-alpha window. Quantize
        # only the display bitmap so partial-alpha pixels cannot blend with
        # the transparent magenta key. The source atlas remains unchanged.
        display.putalpha(display.getchannel('A').point(lambda alpha:255 if alpha>=128 else 0))
    return ImageTk.PhotoImage(display)
