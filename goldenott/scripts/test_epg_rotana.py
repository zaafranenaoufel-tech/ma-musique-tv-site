#!/usr/bin/env python3
"""Offline checks for separate Egyptian and Saudi Rotana programme guides."""
import datetime as dt
import unittest
import official_rotana as r

class RotanaTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime(2026,11,6,12,tzinfo=dt.timezone.utc)
        self.html="""<div class="hour">
        <div class="bg" id="item-06-11-2026">Friday</div>
        <div class="iq-accordion"><div class="iq-accordion-title">
        <h5 class="big-title"><span>21:00</span><span>الفيلم الأول</span></h5>
        </div></div>
        <div class="iq-accordion"><div class="iq-accordion-title">
        <h5 class="big-title"><span>22:45</span><span>الفيلم الثاني</span></h5>
        </div></div>
        <div class="bg" id="item-07-11-2026">Saturday</div>
        <div class="iq-accordion"><div class="iq-accordion-title">
        <h5 class="big-title"><span>00:30</span><span>الفيلم الثالث</span></h5>
        </div></div></div>"""

    def test_saudian_timezone_and_egypt_identity(self):
        rows=r.parse_official_rotana(self.html,"rotanacinema.sa",self.now)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0].get("channel"),"rotanacinema.sa")
        self.assertEqual(rows[0].get("start"),"20261106180000 +0000")
        self.assertEqual(rows[0].get("stop"),"20261106194500 +0000")
        self.assertEqual(rows[0].findtext("title"),"الفيلم الأول")

    def test_no_fake_times_on_empty_html(self):
        self.assertEqual(r.parse_official_rotana("<html></html>","rotanacinema.eg",self.now),[])

    def test_no_fake_times_on_stale_programme(self):
        stale=self.html.replace("2026","2024")
        self.assertEqual(r.parse_official_rotana(stale,"rotanacinema.eg",self.now),[])

if __name__=="__main__":
    unittest.main()
