"""Trusted local composition only; never takes profile paths from a peer body."""
from pathlib import Path
import sys
SOURCE=Path(__file__).resolve().parents[2]/'src'
if str(SOURCE) not in sys.path:sys.path.insert(0,str(SOURCE))
from workbench.agent_memory.transfer import ExportStore,PendingSnapshot,FORMAT

def attach(profile,source_config=None):return ExportStore(profile,source_config)
