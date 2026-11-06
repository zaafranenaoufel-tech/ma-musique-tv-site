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
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from official_national import fetch_national_channel

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

def process(path,wanted,now,fragment,exclude=None):
    exclude=exclude or set()
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
                                if oid in exclude:continue
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


def parse_official_time(value):
    if not isinstance(value,str):return None
    try:
        val=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
        if val.tzinfo is None:val=val.replace(tzinfo=UTC)
        return val.astimezone(UTC)
    except (ValueError,OverflowError):return None

def parse_official_rows(data,output_id,now):
    """BeIN published TV-event rows; only dated entries are accepted."""
    if not isinstance(data,dict) or not isinstance(data.get("rows"),list):return []
    result=[]
    seen=set()
    lower,upper=now-dt.timedelta(hours=6),now+dt.timedelta(days=3)
    for item in data["rows"]:
        if not isinstance(item,dict):continue
        start=parse_official_time(item.get("startDate"))
        stop=parse_official_time(item.get("endDate"))
        title=item.get("title")
        if not isinstance(title,str) or not title.strip():continue
        if not start or not stop or not (start<stop and stop>lower and start<upper):continue
        if stop-start>dt.timedelta(days=2):continue
        key=(start,stop,title)
        if key in seen:continue
        seen.add(key)
        p=ET.Element("programme",{
            "channel":output_id,
            "start":start.strftime("%Y%m%d%H%M%S +0000"),
            "stop":stop.strftime("%Y%m%d%H%M%S +0000")
        })
        ET.SubElement(p,"title").text=title.strip()
        desc=item.get("description")
        if isinstance(desc,str) and desc.strip():
            ET.SubElement(p,"desc").text=desc.strip()[:5000]
        result.append(p)
    return result

def fetch_official_bein(alias,now):
    """Use BeIN's public Opta TV schedule. Fail closed to existing XMLTV source."""
    oid=alias["output_id"]
    site_id=alias["site_id"]
    fmt=lambda t:t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    params=urllib.parse.urlencode({
        "startBefore":fmt(now+dt.timedelta(days=2)),
        "endAfter":fmt(now-dt.timedelta(hours=6)),
        "channelIds":site_id,
    })
    url="https://www.beinsports.com/api/opta/tv-event?"+params
    req=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (compatible; GoldenOTT EPG schedule checker)",
        "Accept":"application/json"
    })
    try:
        with urllib.request.urlopen(req,timeout=14) as response:
            raw=response.read(6_000_001)
        if len(raw)>6_000_000:raise ValueError("official response too large")
        programmes=parse_official_rows(json.loads(raw),oid,now)
        if not programmes:raise ValueError("no valid current TV-event rows")
        return oid,programmes,None
    except Exception as exc:
        return oid,[],str(exc)[:180]

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
    for source in cfg.get("official_national",[]):
        oid=source.get("output_id","")
        name=source.get("name","")
        if oid and name and name not in display[oid]:display[oid].append(name)
    now=dt.datetime.now(UTC)
    counts=defaultdict(int)
    successful=[]
    failed=[]
    with tempfile.TemporaryDirectory(prefix="goldenott-epg-") as d:
        d=Path(d)
        fragment=d/"programmes.xml"
        official_done=set()
        official_errors={}
        official_count=0
        national_done=set()
        national_errors={}
        national_count=0
        with fragment.open("wb") as output:
            national_targets=cfg.get("official_national",[])
            if national_targets:
                with ThreadPoolExecutor(max_workers=6) as pool:
                    futures=[pool.submit(fetch_national_channel,a,now) for a in national_targets]
                    for future in as_completed(futures):
                        try:
                            oid,entries,error=future.result()
                        except Exception as exc:
                            print("OFFICIAL NATIONAL ERROR:",str(exc)[:200],flush=True)
                            continue
                        if error:
                            national_errors[oid]=error
                            continue
                        national_done.add(oid)
                        for entry in entries:
                            output.write(ET.tostring(entry,encoding="utf-8")+b"\n")
                            counts[oid]+=1
                            national_count+=1
            official_done.update(national_done)
            official_targets=cfg.get("official_bein",[])
            if official_targets:
                with ThreadPoolExecutor(max_workers=4) as pool:
                    futures=[pool.submit(fetch_official_bein,a,now) for a in official_targets]
                    for future in as_completed(futures):
                        oid,entries,error=future.result()
                        if error:
                            official_errors[oid]=error
                            continue
                        official_done.add(oid)
                        for entry in entries:
                            output.write(ET.tostring(entry,encoding="utf-8")+b"\n")
                            counts[oid]+=1
                            official_count+=1
            for key,guide in cfg["sources"].items():
                if key not in targets:continue
                try:
                    local=d/(key+".xml.gz")
                    download(guide,local)
                    found,names=process(local,targets[key],now,output,exclude=official_done)
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
      "official_bein_channels":len(official_done-national_done),
      "official_national_channels":len(national_done),
      "official_national_programmes":national_count,
      "official_national_attempted":len(cfg.get("official_national",[])),
      "official_national_failures":national_errors,
      "official_bein_programmes":official_count,
      "official_bein_attempted":len(cfg.get("official_bein",[])),
      "official_bein_failures":official_errors,
      "warning":"Guide scheduling is not a guarantee of live IPTV broadcast. Unmapped Xtream channels need separate associations."
    }
    STATUS.write_text(json.dumps(status,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(status,ensure_ascii=False),flush=True)

if __name__=="__main__":main()
