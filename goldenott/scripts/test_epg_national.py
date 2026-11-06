#!/usr/bin/env python3
"""Offline tests: official French, Italian, Swiss EPG parsing and timezone."""
import datetime as dt
import unittest
from unittest.mock import patch
import official_national as n

class OfficialNationalEPGTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime(2026,11,6,12,tzinfo=dt.timezone.utc)

    def test_rai_minutes_with_unit(self):
        fixture={"events":[{"name":"Film Rai","hour":"19:40",
            "duration_in_minutes":"50 min","duration":"00:50:00"}]}
        with patch.object(n,"read_json",return_value=fixture):
            oid,items,err=n.fetch_national_channel({
                "output_id":"rai2.it","provider":"raiplay.it","site_id":"rai-2"},self.now)
        self.assertIsNone(err)
        self.assertEqual(oid,"rai2.it")
        self.assertEqual(len(items),2)
        self.assertEqual(items[0].findtext("title"),"Film Rai")
        # Italy is UTC+1 in November
        self.assertEqual(items[0].get("start"),"20261106184000 +0000")

    def test_france_official_schedule(self):
        fixture=[{"content":{"title":"Journal","titleLeading":"France 2",
            "broadcastBeginDate":"20h45","duration":"1 h 30 min"}}]
        with patch.object(n,"read_json",return_value=fixture):
            oid,items,err=n.fetch_national_channel({
                "output_id":"france2.fr","provider":"france.tv","site_id":"france-2"},self.now)
        self.assertIsNone(err)
        self.assertEqual(oid,"france2.fr")
        self.assertTrue(any(i.get("start")=="20261106194500 +0000" for i in items))

    def test_swiss_rts_iso_offset(self):
        fixture={"programGuide":[{"channel":{"id":"test-channel"},
            "programList":[{"title":"RTS info","startTime":"2026-11-06T20:45:00+01:00",
                            "endTime":"2026-11-06T21:15:00+01:00"}]}]}
        with patch.object(n,"read_json",return_value=fixture):
            oid,items,err=n.fetch_national_channel({
                "output_id":"rts1.ch","provider":"rts.ch","site_id":"test-channel"},self.now)
        self.assertIsNone(err)
        self.assertEqual(len(items),1)
        self.assertEqual(items[0].get("start"),"20261106194500 +0000")

    def test_bad_source_never_fabricates_programmes(self):
        with patch.object(n,"read_json",side_effect=ValueError("bad source")):
            oid,items,err=n.fetch_national_channel({
                "output_id":"rai1.it","provider":"raiplay.it","site_id":"rai-1"},self.now)
        self.assertEqual(items,[])
        self.assertTrue(err)

if __name__=="__main__":
    unittest.main()
