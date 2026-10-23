"""Local stdio entry. Setup is explicit; loading the plugin never installs packages."""
import json,os,subprocess,sys
from paths import DATA,ROOT,python
def main():
    config=DATA/'settings.json'
    if not config.is_file() or not python().is_file():raise SystemExit('请先运行插件的安装.cmd准备本机依赖。')
    raise SystemExit(subprocess.call([str(python()),str(ROOT/'bridge/server.py'),'--config',str(config)],cwd=ROOT/'bridge'))
if __name__=='__main__':main()
