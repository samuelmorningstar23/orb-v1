import sys, json, hashlib, contextlib
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
def guard(event,args):
    if event in ("socket.connect", "socket.getaddrinfo"):
        raise RuntimeError("Network forbidden in offline map build")
sys.addaudithook(guard)
from replay.build_maps import main
for event in ["Austria", "Barcelona", "Australia", "Japan", "Belgium", "Netherlands"]:
    log=Path("out/maps")/(event+"_build.log")
    with log.open("w") as f, contextlib.redirect_stdout(f),contextlib.redirect_stderr(f):
        result=main(["--event",event,"--year","2026","--cache","/private/tmp/orb-map-cache","--offline","--geometry-only"])
    print(event,result,flush=True)
