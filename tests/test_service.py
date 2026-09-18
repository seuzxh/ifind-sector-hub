# -*- coding: utf-8 -*-
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest import mock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ifind_sector_hub import SectorHub, HubConfig, TokenStore
from ifind_sector_hub.service import build_router


def make_app(tmpdir):
    hub = SectorHub(HubConfig(db_path=os.path.join(tmpdir, "x.db"),
                              access_token="at", refresh_token="rt"))
    hub.store.save_concept_dict([
        {"concept_code": "885001.TI", "short_name": "人工智能"}])
    hub.store.save_concept_members("885001.TI", [
        {"stock_code": "600519.SH", "stock_name": "贵州茅台"}], "20260917")
    app = FastAPI()
    app.include_router(build_router(hub))
    return TestClient(app), hub


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.client, self.hub = make_app(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_concepts_endpoint(self):
        r = self.client.get("/concepts")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"count": 1,
                                    "concepts": [{"concept_code": "885001.TI", "concept_name": "人工智能"}]})

    def test_members_endpoint(self):
        r = self.client.get("/concepts/885001.TI/members")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["members"][0]["stock_code"], "600519.SH")

    def test_sync_members_endpoint_triggers_sync(self):
        with mock.patch.object(self.hub.sync, "sync_concept_members", return_value=3) as s:
            r = self.client.post("/sync/members", json={"concept_codes": ["885001.TI"], "date": "20260917"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True, "saved_records": 3})
        s.assert_called_once_with(["885001.TI"], "20260917")


if __name__ == "__main__":
    unittest.main()
