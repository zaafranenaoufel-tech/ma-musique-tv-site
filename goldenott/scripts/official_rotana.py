#!/usr/bin/env python3
"""Official Rotana TV guide parser: channel-specific Saudi-zone programme times.

No subscriber credentials or IPTV streams are accessed. The website may return
an old or partial schedule: only events dated within the current guide window
are accepted. All failures fall back to the previous XMLTV source.
"""
import datetime as dt
import re
import urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

UTC=dt.timezone.utc
RIYADH=ZoneInfo("Asia/Riyadh")
DATE_RE=re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})$")
CLOCK_RE=re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")

def parse_official_rotana(html,oid,now):
    soup=BeautifulSoup(html,"html.parser")
    events=[]
    day=None
    for block in soup.select(".hour > div"):
        classes=block.get("class",[])
        if "bg" in classes:
            found=DATE_RE.search(block.get("id",""))
            if found:
                d,m,y=(int(z) for z in found.groups())
                try:day=dt.date(y,m,d)
                except ValueError:day=None
            else:day=None
            continue
        if "iq-accordion" not in classes or day is None:continue
        titlebox=block.select_one(".iq-accordion-title .big-title")
        if titlebox is None:continue
        spans=titlebox.select("span")
        if len(spans)<2:continue
        match=CLOCK_RE.fullmatch(spans[0].get_text(" ",strip=True))
        title=spans[1].get_text(" ",strip=True)
        if not match or not title:continue
        hour,minute=(int(z) for z in match.groups())
        if hour>23 or minute>59:continue
        try:
            start=dt.datetime(day.year,day.month,day.day,hour,minute,tzinfo=RIYADH).astimezone(UTC)
        except ValueError:continue
        events.append((start,title))
    events=sorted(set(events),key=lambda x:x[0])
    if len(events)<2:return []
    lower=now-dt.timedelta(hours=6)
    upper=now+dt.timedelta(days=3)
    programmes=[]
    for idx,(start,title) in enumerate(events[:-1]):
        stop=events[idx+1][0]
        if not (start<stop and stop-start<=dt.timedelta(hours=16)):continue
        if start>=upper or stop<=lower:continue
        event=ET.Element("programme",{
            "channel":oid,
            "start":start.strftime("%Y%m%d%H%M%S +0000"),
            "stop":stop.strftime("%Y%m%d%H%M%S +0000")
        })
        ET.SubElement(event,"title",{"lang":"ar"}).text=title
        programmes.append(event)
    return programmes

def fetch_official_rotana(item,now):
    oid=item["output_id"]
    channel=str(item["site_id"])
    if not channel.isdigit():return oid,[],"Invalid Rotana channel ID"
    url="https://rotana.net/ar/streams?channel="+channel+"&tz="
    request=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (compatible; GoldenOTT EPG official guide)",
        "Accept":"text/html"
    })
    try:
        with urllib.request.urlopen(request,timeout=18) as response:
            raw=response.read(4_000_001)
        if len(raw)>4_000_000:raise ValueError("Rotana page too large")
        programmes=parse_official_rotana(raw,oid,now)
        if not programmes:raise ValueError("No current programme schedule published")
        return oid,programmes,None
    except Exception as exc:
        return oid,[],str(exc)[:180]
