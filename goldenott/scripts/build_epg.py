#!/usr/bin/env python3
"""XMLTV public programmes mapped to existing Xtream EPG channel identifiers.
Never retrieves Xtream credentials, streams, playlists, or application data.
"""
import copy
import datetime as dt
import gzip
import html
import json
import os
import re
import shutil
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MAP=ROOT/"mapping.json"
OUT=ROOT/"guide.xml.gz"
STATUS=ROOT/"status.json"
UTC=dt.timezone.utc

def timestamp(value):
    if not value or not re.match(r"^\d{14}",value):return None
    try:
        out=dt.datetime.strptime(value[:14],"%Y%m%d%H%M%S")
        off=value[14:].strip()
        if re.fullmatch(r"[+-]\d{4}",off):
            mins=int(off[1:3])*60+int(off[3:])
            if off[0]=="-":mins=-mins
            out=out.replace(tzinfo=dt.timezone(dt.timedelta(minutes=mins)))
        else:out=out.replace(tzinfo=UTC)
        return out.astimezone(UTC)
    except (ValueError,OverflowError):return None

def download(url,path,limit=100_000_000):
    if not url.startswith("https://"):raise ValueError("HTTPS required")
    req=urllib.request.Request(url,headers={"User-Agent":"GoldenOTT-EPG/1.0"})
    size=0
    with urllib.request.urlopen(req,timeout=100) as resp,open(path,"wb") as out:
        while True:
            b=resp.read(131072)
            if not b:break
            size+=len(b)
            if size>limit:raise ValueError("Source exceeds size limit")
            out.write(b)
    if size<100:raise ValueError("Source is empty")

def process(path,wanted,now,fragment):
    with open(path,"rb") as f: gz=f.read(2)==b"\x1f\x8b"
    source=gzip.open(path,"rb") if gz else open(path,"rb")
    counters=defaultdict(int)
    seen=set()
    names=defaultdict(list)
    lower=now-dt.timedelta(hours=6)
    upper=now+dt.timedelta(days=7)
    with source as stream:
        root=None
        for event,element in ET.iterparse(stream,events=("start","end")):
            if root is None and event=="start":root=element
            if event!="end":continue
            if element.tag=="channel":
                sid=element.get("id","")
                if sid in wanted:
                    names[sid]=[v.text.strip() for v in element.findall("display-name") if v.text]
            elif element.tag=="programme":
                sid=element.get("channel","")
                if sid in wanted:
                    start=timestamp(element.get("start"))
                    stop=timestamp(element.get("stop"))
                    if start and stop and start<stop and stop>lower and start<upper:
                        if (element.findtext("title") or "").strip():
                            for oid in wanted[sid]:
                                dup=(oid,element.get("start"),element.get("stop"),element.findtext("title"))
                                if dup in seen:continue
                                seen.add(dup)
                                entry=copy.deepcopy(element)
                                entry.set("channel",oid)
                                fragment.write(ET.tostring(entry,encoding="utf-8")+b"\n")
                                counters[oid]+=1
            if element.tag in ("channel","programme"):
                element.clear()
                if root is not None and root is not element:root.clear()
    return counters,names

def main():
    cfg=json.loads(MAP.read_text(encoding="utf-8"))
    targets=defaultdict(lambda:defaultdict(list))
    display=defaultdict(list)
    for alias in cfg.get("aliases",[]):
        oid=alias.get("output_id","")
        sid=alias.get("source_id","")
        key=alias.get("source","")
        if not oid or not sid or key not in cfg["sources"]:continue
        if oid not in targets[key][sid]:targets[key][sid].append(oid)
        name=alias.get("name","")
        if name and name not in display[oid]:display[oid].append(name)
    now=dt.datetime.now(UTC)
    counts=defaultdict(int)
    successful=[]
    failed=[]
    with tempfile.TemporaryDirectory(prefix="goldenott-epg-") as d:
        d=Path(d)
        fragment=d/"programmes.xml"
        with fragment.open("wb") as output:
            for key,guide in cfg["sources"].items():
                if key not in targets:continue
                try:
                    local=d/(key+".xml.gz")
                    download(guide,local)
                    found,names=process(local,targets[key],now,output)
                    successful.append(key)
                    for oid,count in found.items():counts[oid]+=count
                    for sid,source_names in names.items():
                        for oid in targets[key][sid]:
                            for name in source_names:
                                if name not in display[oid]:display[oid].append(name)
                except Exception as exc:
                    print("SOURCE ERROR:",key,str(exc)[:250],flush=True)
                    failed.append(key)
        good=sorted(oid for oid,count in counts.items() if count>0)
        if not good:raise RuntimeError("No current programmes: refusing to replace the current guide")
        temp=d/"guide.xml.gz"
        with gzip.open(temp,"wb",compresslevel=7) as out:
            out.write(b'<?xml version="1.0" encoding="UTF-8"?>\n<tv generator-info-name="GoldenOTT Custom EPG">\n')
            for oid in good:
                out.write(('  <channel id="'+html.escape(oid,quote=True)+'">\n').encode("utf-8"))
                for name in display[oid] or [oid]:
                    out.write(("    <display-name>"+html.escape(name)+"</display-name>\n").encode("utf-8"))
                out.write(b"  </channel>\n")
            with fragment.open("rb") as stream:shutil.copyfileobj(stream,out)
            out.write(b"</tv>\n")
        with gzip.open(temp,"rb") as stream:ET.parse(stream)
        shutil.copyfile(temp,OUT)
    status={
      "updated_utc":now.isoformat(),
      "channels_with_programmes":len(good),
      "programmes":sum(counts.values()),
      "sources_downloaded":successful,
      "sources_failed":failed,
      "target_aliases":len(cfg.get("aliases",[])),
      "warning":"Guide scheduling is not a guarantee of live IPTV broadcast. Unmapped Xtream channels need separate associations."
    }
    STATUS.write_text(json.dumps(status,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(status,ensure_ascii=False),flush=True)

if __name__=="__main__":main()
