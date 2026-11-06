#!/usr/bin/env python3
"""Passerelle EPG FreeboxOS -> XMLTV pour GoldenOTT, lecture seule et locale.
Ne change ni playlists, ni favoris, ni configuration de la Freebox.
Python 3, aucune bibliothèque supplémentaire.
"""
import argparse, datetime, gzip, html, io, json, os, re, sys, tempfile, threading, time, unicodedata
import urllib.request
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from xml.etree import ElementTree as ET

API="http://mafreebox.freebox.fr/api/v16"
MAPPING="https://raw.githubusercontent.com/zaafranenaoufel-tech/ma-musique-tv-site/main/goldenott/mapping.json"
UTC=datetime.timezone.utc
MAX=6000000

def fetch(url,limit=MAX,timeout=18):
    req=urllib.request.Request(url,headers={"User-Agent":"FreeboxEPG/1.1"})
    with urllib.request.urlopen(req,timeout=timeout) as response:
        raw=response.read(limit+1)
    if len(raw)>limit: raise ValueError("Réponse trop volumineuse")
    return json.loads(raw)

def freebox(path,base=API):
    if not (base.startswith("http://mafreebox.freebox.fr/api/v") or base.startswith("http://127.0.0.1:")):
        raise ValueError("Uniquement le serveur Freebox du réseau local")
    if not path.startswith("/") or ".." in path: raise ValueError("Chemin invalide")
    response=fetch(base.rstrip("/")+path)
    if not isinstance(response,dict) or response.get("success") is not True:
        raise ValueError("Freebox : réponse invalide")
    return response.get("result",{})

def normalize(value):
    value=unicodedata.normalize("NFKD",str(value)).encode("ascii","ignore").decode().casefold()
    value=re.sub(r"^\s*fr\s*[-|:]\s*","",value)
    value=re.sub(r"\b(fhd|hd|sd|uhd|hevc|4k|h264|h265|hdr)\b"," ",value)
    return " ".join(re.findall(r"[a-z0-9]+",value))

def channels(base):
    raw=freebox("/tv/channels/",base)
    if not isinstance(raw,dict): raise ValueError("Liste Freebox illisible")
    return {u:d for u,d in raw.items() if u.startswith("uuid-webtv-") and isinstance(d,dict) and d.get("name")}

def programmes(raw,known,begin,end):
    result=defaultdict(dict)
    if not isinstance(raw,dict):return result
    for uuid,blocks in raw.items():
        if uuid not in known or not isinstance(blocks,dict):continue
        for entry in blocks.values():
            if not isinstance(entry,dict):continue
            title=entry.get("title") or entry.get("name")
            if not isinstance(title,str) or not title.strip():continue
            try: start=int(entry["date"]); duration=int(entry["duration"])
            except (ValueError,TypeError,KeyError):continue
            stop=start+duration
            if not (1500000000<start and 60<=duration<=57600 and stop>begin-21600 and start<end):continue
            description=entry.get("desc") or entry.get("description") or ""
            if not isinstance(description,str):description=""
            title=" ".join(title.split())
            if len(title)>500:continue
            if duration>=7200 and normalize(title)==normalize(known[uuid]["name"]) and not description:continue
            result[uuid][(start,stop,title)]=(start,stop,title,description[:5000])
    return result

def aliases(known):
    # Alias .fr uniquement, avec nom EXACT. Rejette les noms ambigus.
    matches=defaultdict(set)
    for uuid,data in known.items():
        for key in ("name","short_name"):
            name=normalize(data.get(key,""))
            if name:matches[name].add(uuid)
    output=defaultdict(set)
    diagnostics={"aliases":0,"source":"non disponible"}
    try:
        cfg=fetch(MAPPING,limit=500000,timeout=12)
        origin=defaultdict(set)
        for item in cfg.get("aliases",[]):
            oid=str(item.get("output_id",""))
            label=str(item.get("name",""))
            if not oid.endswith(".fr") or not label.upper().startswith("FR - "):continue
            for name in [label]+[x for x in item.get("display_names",[]) if isinstance(x,str)]:
                c=matches.get(normalize(name),set())
                if len(c)==1:
                    u=next(iter(c))
                    output[u].add(oid)
                    origin[oid.lower()].add(u)
        conflicting={oid for oid,us in origin.items() if len(us)>1}
        for u in output:output[u]={x for x in output[u] if x.lower() not in conflicting}
        diagnostics={"aliases":sum(map(len,output.values())),"source":"mapping GitHub","conflits_exclus":len(conflicting)}
    except Exception as exc:
        diagnostics={"aliases":0,"source":"indisponible","detail":str(exc)[:90]}
    return output,diagnostics

def xml_date(timestamp):
    return datetime.datetime.fromtimestamp(timestamp,UTC).strftime("%Y%m%d%H%M%S +0000")

def convert(known,events,mapped):
    tv=ET.Element("tv",{"generator-info-name":"Freebox EPG - passerelle locale"})
    for uuid in sorted(events):
        if not events[uuid]:continue
        outputs=["freebox."+uuid]+sorted(mapped.get(uuid,set()))
        for oid in outputs:
            ch=ET.SubElement(tv,"channel",{"id":oid})
            ET.SubElement(ch,"display-name").text=str(known[uuid]["name"])
            if known[uuid].get("short_name") and known[uuid]["short_name"]!=known[uuid]["name"]:
                ET.SubElement(ch,"display-name").text=str(known[uuid]["short_name"])
        for start,stop,title,desc in sorted(events[uuid].values()):
            for oid in outputs:
                p=ET.SubElement(tv,"programme",{"channel":oid,"start":xml_date(start),"stop":xml_date(stop)})
                ET.SubElement(p,"title").text=title
                if desc:ET.SubElement(p,"desc").text=desc
    return ET.tostring(tv,encoding="utf-8",xml_declaration=True)

def write_atomic(path,content):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=".freebox-epg-",dir=str(path.parent))
    try:
        with os.fdopen(fd,"wb") as f:f.write(content)
        os.replace(tmp,str(path))
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def update(base=API,folder=Path("."),hours=48):
    known=channels(base)
    if not known:raise ValueError("Aucune chaîne Freebox disponible")
    now=int(time.time()); begin=now-3600; end=now+hours*3600
    events=defaultdict(dict); failed=[]
    for timestamp in range(begin,end+1,4*3600):
        try:
            raw=freebox("/tv/epg/by_time/"+str(timestamp),base)
            sample=programmes(raw,known,begin,end)
            for uuid,rows in sample.items():events[uuid].update(rows)
        except Exception as exc:failed.append(str(exc)[:90])
        time.sleep(0.08)
    count=sum(len(v) for v in events.values())
    if not count:raise RuntimeError("Aucun programme réel : ancien guide conservé")
    matched,source=aliases(known)
    xml=convert(known,events,matched)
    ET.fromstring(xml)  # Refuser une génération invalide
    out=folder/"guide.xml.gz"
    write_atomic(out,gzip.compress(xml,compresslevel=6,mtime=0))
    stats={"maj_utc":datetime.datetime.now(UTC).isoformat(),
        "chaines_freebox":len(known),
        "chaines_avec_programmes":sum(bool(x) for x in events.values()),
        "programmes_uniques":count,"association":source,
        "echantillons_echoues":len(failed),
        "limite":"Ne couvre pas les chaînes absentes de Freebox. Ne modifie pas les associations GoldenOTT."}
    write_atomic(folder/"status.json",json.dumps(stats,ensure_ascii=False,indent=2).encode())
    return stats

class Server(BaseHTTPRequestHandler):
    folder=Path(".")
    def do_GET(self):
        paths={"/guide.xml.gz":"guide.xml.gz","/guide.xml":"guide.xml.gz","/status":"status.json"}
        name=paths.get(self.path)
        if name is None:self.send_error(404);return
        try:
            content=(self.folder/name).read_bytes()
            if self.path=="/guide.xml":content=gzip.decompress(content)
        except Exception:self.send_error(503,"EPG non prêt");return
        self.send_response(200)
        self.send_header("Content-Type","application/json" if self.path=="/status" else "application/xml" if self.path=="/guide.xml" else "application/gzip")
        self.send_header("Content-Length",str(len(content)))
        self.end_headers()
        try:self.wfile.write(content)
        except BrokenPipeError:pass
    def log_message(self,*args):pass

def main():
    parser=argparse.ArgumentParser(description="Freebox EPG local pour GoldenOTT, sans modifier ta playlist")
    parser.add_argument("action",nargs="?",choices=("probe","export","serve"),default="serve")
    parser.add_argument("--base",default=API)
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--listen",default="0.0.0.0")
    parser.add_argument("--hours",type=int,default=48)
    parser.add_argument("--refresh",type=int,default=6)
    args=parser.parse_args()
    if args.hours<12 or args.hours>120:parser.error("12 à 120 heures")
    try:
        if args.action=="probe":
            known=channels(args.base)
            sample=programmes(freebox("/tv/epg/by_time/"+str(int(time.time())),args.base),known,int(time.time())-7200,int(time.time())+86400)
            print(json.dumps({"chaines":len(known),"programmes_echantillon":sum(map(len,sample.values())),"exemples":[{"chaine":known[u]["name"],"emission":next(iter(v.values()))[2]} for u,v in list(sample.items())[:5] if v]},ensure_ascii=False,indent=2))
            return
        folder=Path.home()/"freebox_epg"
        print("Récupération des vrais programmes Freebox en cours...",flush=True)
        print(json.dumps(update(args.base,folder,args.hours),ensure_ascii=False,indent=2),flush=True)
        if args.action=="export":
            print("Fichier prêt :",folder/"guide.xml.gz");return
        Server.folder=folder
        web=ThreadingHTTPServer((args.listen,args.port),Server)
        print("GUIDE PRÊT : http://ADRESSE_IP_IPHONE:"+str(args.port)+"/guide.xml.gz",flush=True)
        print("Laisser iSH ouvert : iOS peut suspendre ce serveur en arrière-plan.",flush=True)
        def refresh():
            while True:
                time.sleep(args.refresh*3600)
                try:update(args.base,folder,args.hours)
                except Exception as exc:print("Ancien guide conservé:",exc,file=sys.stderr,flush=True)
        threading.Thread(target=refresh,daemon=True).start()
        web.serve_forever()
    except KeyboardInterrupt:print("Serveur arrêté")
    except Exception as exc:print("ERREUR:",exc,file=sys.stderr);sys.exit(1)

if __name__=="__main__":main()
