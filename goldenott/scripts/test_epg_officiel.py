#!/usr/bin/env python3
"""Network-free tests of official schedule validation and safe fallback."""
import datetime as dt
import io
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import build_epg as b

class OfficialEPGTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime(2026,11,6,12,tzinfo=dt.timezone.utc)

    def test_official_programmes_are_dated_and_deduplicated(self):
        row={"startDate":"2026-11-06T20:45:00Z","endDate":"2026-11-06T22:45:00Z","title":"Match officiel","description":"Sport"}
        got=b.parse_official_rows({"rows":[row,row,{"title":"sans heures"}]},"beinsports1.fr",self.now)
        self.assertEqual(len(got),1)
        self.assertEqual(got[0].get("channel"),"beinsports1.fr")
        self.assertEqual(got[0].get("start"),"20261106204500 +0000")
        self.assertEqual(got[0].findtext("title"),"Match officiel")

    def test_timezone_conversion_and_bad_response(self):
        row={"startDate":"2026-11-06T21:45:00+01:00","endDate":"2026-11-06T23:45:00+01:00","title":"Film"}
        got=b.parse_official_rows({"rows":[row]},"a",self.now)
        self.assertEqual(got[0].get("start"),"20261106204500 +0000")
        self.assertEqual(b.parse_official_rows({"rows":[]},"a",self.now),[])
        self.assertEqual(b.parse_official_rows({"wrong":[] },"a",self.now),[])

    def test_official_wins_and_xmltv_fallback_remains(self):
        xml=b'''<?xml version="1.0"?><tv><channel id="s"><display-name>S</display-name></channel><programme channel="s" start="20261106110000 +0000" stop="20261106220000 +0000"><title>Legacy</title></programme></tv>'''
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"test.xml"
            p.write_bytes(xml)
            out=io.BytesIO()
            c,_=b.process(p,{"s":["beinsports1.fr"]},self.now,out,exclude={"beinsports1.fr"})
            self.assertEqual(dict(c),{})
            self.assertEqual(out.getvalue(),b"")
            out2=io.BytesIO()
            c2,_=b.process(p,{"s":["beinsports1.fr"]},self.now,out2)
            self.assertEqual(c2["beinsports1.fr"],1)
            self.assertIn(b"Legacy",out2.getvalue())

if __name__=="__main__":
    unittest.main()
