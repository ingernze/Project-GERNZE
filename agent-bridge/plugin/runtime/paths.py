import os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('GERNZE_PLUGIN_DATA') or Path(os.environ.get('LOCALAPPDATA') or Path.home())/'GERNZE/CodexPlugin')
def python():
    return DATA/'runtime'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
