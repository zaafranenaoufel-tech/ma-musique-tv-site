#!/usr/bin/env python3
"""Read dated schedules directly from public broadcaster TV guides.

No Xtream credentials, stream links or subscriber data are used.
A source that is unavailable or returns malformed/ambiguous dates yields no
programmes; the build script then preserves the existing XMLTV fallback.
"""
import datetime as dt
import json
import re
import urllib.request
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

UTC=dt.timezone.utc
PARIS=ZoneInfo("Europe/Paris")
ROME=ZoneInfo("Europe/Rome")
CH=ZoneInfo("Europe/Zurich")

def read_json(url):
    if not url.startswith("https://"):raise ValueError("HTTPS required")
    request=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (compatible; GoldenOTT EPG; public schedules)",
        "Accept":"application/json"
    })
    with urllib.request.urlopen(request,timeout=14) as response:
        data=response.read(4_000_001)
    if len(data)>4_000_000:raise ValueError("Official programme response too big")
    return json.loads(data)

def local_time(day,time_text,zone):
    match=re.fullmatch(r"\s*(\d{1,2})(?::|h)(\d{1,2})\s*",str(time_text))
    if not match:raise ValueError("Bad local time")
    h,m=map(int,match.groups())
    if h>23 or m>59:raise ValueError("Bad clock")
    return dt.datetime(day.year,day.month,day.day,h,m,tzinfo=zone).astimezone(UTC)

def iso_time(value):
    if not value or not isinstance(value,str):raise ValueError("Missing ISO time")
    timestamp=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
    if timestamp.tzinfo is None:raise ValueError("Missing timezone")
    return timestamp.astimezone(UTC)

def valid_entry(oid,start,stop,title,now,description=""):
    if not isinstance(title,str) or not title.strip():return None
    if start is None or stop is None:return None
    if stop<=start or stop-start>dt.timedelta(hours=16):return None
    if stop<=now-dt.timedelta(hours=6) or start>=now+dt.timedelta(days=3):return None
    p=ET.Element("programme",{
       "channel":oid,"start":start.strftime("%Y%m%d%H%M%S +0000"),
       "stop":stop.strftime("%Y%m%d%H%M%S +0000")
    })
    ET.SubElement(p,"title").text=title.strip()
    if isinstance(description,str) and description.strip():
        ET.SubElement(p,"desc").text=description.strip()[:5000]
    return p

def france_schedule(oid,site_id,now):
    # France.tv EPG's broadcast day is 06:00 through 05:59 next day,
    # with hours displayed in France local time.
    found=[]
    today=now.astimezone(PARIS).date()
    for offset in (-1,0,1):
        day=today+dt.timedelta(days=offset)
        url="https://www.france.tv/api/epg/videos/?date="+day.isoformat()+"&channel="+site_id
        data=read_json(url)
        if not isinstance(data,list):raise ValueError("France.tv response is not a list")
        for row in data:
            if not isinstance(row,dict):continue
            info=row.get("content")
            if not isinstance(info,dict):continue
            title=info.get("title","")
            leading=info.get("titleLeading","")
            if isinstance(leading,str) and leading.strip():title=leading.strip()+" - "+str(title)
            time_text=info.get("broadcastBeginDate","")
            duration_text=info.get("duration","")
            if not isinstance(duration_text,str):continue
            units=re.findall(r"(\d+)\s*(h|min|s)\b",duration_text)
            length=sum(int(v)*{"h":3600,"min":60,"s":1}[unit] for v,unit in units)
            if not (0<length<=16*3600):continue
            try:
                startday=day
                hh=re.match(r"\s*(\d{1,2})\s*h",str(time_text))
                if not hh:continue
                if int(hh.group(1))<6:startday=day+dt.timedelta(days=1)
                start=local_time(startday,time_text,PARIS)
                entry=valid_entry(oid,start,start+dt.timedelta(seconds=length),title,now,info.get("description",""))
                if entry is not None:found.append(entry)
            except (ValueError,OverflowError):continue
    return found

def rai_schedule(oid,site_id,now):
    found=[]
    today=now.astimezone(ROME).date()
    for offset in (0,1):
        day=today+dt.timedelta(days=offset)
        url="https://www.raiplay.it/palinsesto/app/"+site_id+"/"+day.strftime("%d-%m-%Y")+".json"
        data=read_json(url)
        events=data.get("events",[]) if isinstance(data,dict) else []
        if not isinstance(events,list):raise ValueError("RaiPlay events not list")
        for row in events:
            if not isinstance(row,dict):continue
            try:
                raw_minutes=str(row.get("duration_in_minutes","")).strip()
                m=re.fullmatch(r"(\\d+)\\s*(?:min)?",raw_minutes,re.IGNORECASE)
                if m:
                    minutes=int(m.group(1))
                else:
                    # RaiPlay may alternatively publish HH:MM:SS.
                    raw_hms=str(row.get("duration","")).strip()
                    hms=re.fullmatch(r"(\\d{1,2}):(\\d{2}):(\\d{2})",raw_hms)
                    if not hms:continue
                    hours,mins,secs=map(int,hms.groups())
                    minutes=hours*60+mins+(1 if secs>=30 else 0)
                if minutes<=0 or minutes>960:continue
                start=local_time(day,row.get("hour",""),ROME)
                p=valid_entry(oid,start,start+dt.timedelta(minutes=minutes),row.get("name",""),now,row.get("description",""))
                if p is not None:found.append(p)
            except (ValueError,TypeError,OverflowError):continue
    return found

def rts_schedule(oid,site_id,now):
    found=[]
    today=now.astimezone(CH).date()
    for offset in (0,1):
        day=today+dt.timedelta(days=offset)
        url=("https://il.srgssr.ch/integrationlayer/2.0/rts/programGuide/tv/byDate/"
            +day.isoformat()+"?reduced=false&channelId="+site_id)
        data=read_json(url)
        block=data.get("programGuide",[]) if isinstance(data,dict) else []
        if not isinstance(block,list):raise ValueError("RTS programme guide not list")
        for group in block:
            if not isinstance(group,dict):continue
            if str(group.get("channel",{}).get("id",""))!=site_id:continue
            for row in group.get("programList",[]):
                if not isinstance(row,dict):continue
                try:
                    start=iso_time(row.get("startTime"))
                    stop=iso_time(row.get("endTime"))
                    p=valid_entry(oid,start,stop,row.get("title",""),now,row.get("description",""))
                    if p is not None:found.append(p)
                except (ValueError,TypeError,OverflowError):continue
    return found

def fetch_national_channel(item,now):
    oid=item["output_id"]
    try:
        provider=item["provider"]
        site_id=item["site_id"]
        if provider=="france.tv":entries=france_schedule(oid,site_id,now)
        elif provider=="raiplay.it":entries=rai_schedule(oid,site_id,now)
        elif provider=="rts.ch":entries=rts_schedule(oid,site_id,now)
        else:raise ValueError("Unsupported official provider")
        unique={}
        for p in entries:
            key=(p.get("start"),p.get("stop"),p.findtext("title"))
            unique[key]=p
        accepted=[unique[k] for k in sorted(unique)]
        if not accepted:raise ValueError("No current dated programmes")
        return oid,accepted,None
    except Exception as exc:
        return oid,[],str(exc)[:180]
