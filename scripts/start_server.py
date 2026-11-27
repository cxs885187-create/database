"""Start the local vocabulary server detached from this shell.

PowerShell's Start-Process fails in this environment because both NO_PROXY and no_proxy
exist, so the child is spawned through Python's case-insensitive environment instead.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
python = ROOT/'.venv'/'Scripts'/'python.exe'
logs = ROOT/'logs'
logs.mkdir(exist_ok=True)

out = open(logs/'server.out.log','a',encoding='utf-8')
err = open(logs/'server.err.log','a',encoding='utf-8')
flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
proc = subprocess.Popen(
    [str(python),'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000'],
    cwd=str(ROOT),stdout=out,stderr=err,stdin=subprocess.DEVNULL,creationflags=flags,close_fds=True,
)
print('spawned', proc.pid)
