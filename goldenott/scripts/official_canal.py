#!/usr/bin/env python3
"""Canal+ France public TV schedule. Never needs a user account or playlist."""
import datetime as dt
import json
import urllib.parse
import urllib.request
from functools import lru_cache
import xml.etree.ElementTree as ET

UTC=dt.timezone.utc
HEADERS={
  "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
  "Accept":"application/json",
  "Accept-Language":"fr-FR,fr;q=0.7"
}

def json_response(url):
    if not url.startswith("https://"):raise ValueError("HTTPS required")
    req=urllib.request.Request(url,headers=HEADERS)
    with urllib.request.urlopen(req,timeout=14) as response:
        content=response.read(4_000_001)
    if len(content)>4_000_000:raise ValueError("Response too large")
    return json.loads(content)

@lru_cache(maxsize=1)
def access_token():
    url="https://hodor.canalplus.pro/api/v2/mycanal/authenticate.json/webapp/6.0?experiments=beta-test-one-tv-guide:control"
    data=json_response(url)
    token=data.get("token") if isinstance(data,dict) else None
    if not isinstance(token,str) or len(token)<5 or len(token)>1000:
        raise ValueError("CANAL+ public guide token unavailable")
    return token

def date_time(value):
    if not isinstance(value,str):return None
    try:
        t=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
        if t.tzinfo is None:return None
        return t.astimezone(UTC)
    except (ValueError,OverflowError):return None

def parse_canals(data,oid,now):
    if not isinstance(data,dict) or not isinstance(data.get("timeSlices"),list):return []
    slots=[]
    for group in data["timeSlices"]:
        if not isinstance(group,dict):continue
        for entry in group.get("contents",[]):
            if not isinstance(entry,dict):continue
            start=date_time(entry.get("startTime"))
            title=entry.get("title")
            if start is not None and isinstance(title,str) and title.strip():
                slots.append((start,title.strip()))
    slots=sorted(set(slots))
    if not slots:return []
    lower=now-dt.timedelta(hours=6)
    upper=now+dt.timedelta(days=3)
    out=[]
    for index,(start,title) in enumerate(slots[:-1]):
        stop=slots[index+1][0]
        if stop<=start or stop-start>dt.timedelta(hours=16):continue
        if stop<=lower or start>=upper:continue
        p=ET.Element("programme",{
            "channel":oid,"start":start.strftime("%Y%m%d%H%M%S +0000"),
            "stop":stop.strftime("%Y%m%d%H%M%S +0000")
        })
        ET.SubElement(p,"title").text=title
        out.append(p)
    return out

def fetch_official_canal(item,now):
    oid=item["output_id"]
    site_id=str(item["site_id"])
    if not site_id.isdigit():return oid,[],"Invalid CANAL+ channel identifier"
    try:
        token=urllib.parse.quote(access_token(),safe="")
        current=now.astimezone(UTC).date()
        all_slots=[]
        for offset in (0,1,2):
            # API uses the number of broadcast days relative to UTC midnight.
            url=f"https://hodor.canalplus.pro/api/v2/mycanal/channels/{token}/{site_id}/broadcasts/day/{offset}"
            data=json_response(url)
            if not isinstance(data,dict) or not isinstance(data.get("timeSlices"),list):continue
            all_slots.extend(data["timeSlices"])
        if not all_slots:raise ValueError("No official broadcasts available")
        got=parse_canals({"timeSlices":all_slots},oid,now)
        if not got:raise ValueError("No valid current schedule")
        return oid,got,None
    except Exception as exc:
        return oid,[],str(exc)[:180]
