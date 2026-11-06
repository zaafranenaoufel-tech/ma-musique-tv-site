#!/usr/bin/env python3
"""Tests for CANAL+ official public TV schedule parsing."""
import datetime as dt
import unittest
from unittest.mock import patch
import official_canal as c

class OfficialCanalTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime(2026,11,6,12,tzinfo=dt.timezone.utc)

    def test_schedule_uses_exact_iso_hours_without_shift(self):
        fixture={"timeSlices":[{"contents":[
          {"title":"Avant-match","startTime":"2026-11-06T19:00:00+01:00"},
          {"title":"Le match","startTime":"2026-11-06T20:45:00+01:00"},
          {"title":"Après-match","startTime":"2026-11-06T22:45:00+01:00"}
        ]}]}
        items=c.parse_canals(fixture,"canalplusfoot.fr",self.now)
        self.assertEqual(len(items),2)
        self.assertEqual(items[1].get("start"),"20261106194500 +0000")
        self.assertEqual(items[1].findtext("title"),"Le match")
        self.assertEqual(items[1].get("stop"),"20261106214500 +0000")

    def test_invalid_or_empty_response(self):
        self.assertEqual(c.parse_canals({}, "canalplusfoot.fr",self.now),[])
        self.assertEqual(c.parse_canals({"timeSlices":[]}, "canalplusfoot.fr",self.now),[])

    def test_non_matching_token_returns_empty_not_fabricated(self):
        with patch.object(c,"access_token",side_effect=ValueError("token unavailable")):
            oid,items,error=c.fetch_official_canal({"output_id":"canalplusfoot.fr","site_id":"1045"},self.now)
        self.assertEqual(oid,"canalplusfoot.fr")
        self.assertEqual(items,[])
        self.assertTrue(error)

if __name__=="__main__":
    unittest.main()
