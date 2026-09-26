# -*- coding: utf-8 -*-
import os, json, tempfile

import unittest
from unittest import mock
from ifind_sector_hub.core import tokens as tk


def _ok_response(new_at, new_rt=None):
    resp = mock.Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"errorcode": 0, "data": {
        "access_token": new_at, "refresh_token": new_rt, "expired_time": "2099-01-01"}}
    return resp


class TokenStoreTests(unittest.TestCase):
    def test_refresh_returns_new_token_and_persists_rotation(self):
        store = tk.TokenStore(access_token="old-at", refresh_token="rt1")
        with mock.patch.object(tk.requests, "post", return_value=_ok_response("new-at", "rt2")) as p:
            got = store.refresh_access_token("old-at")
        self.assertEqual(got, "new-at")
        self.assertEqual(store.refresh_token, "rt2")  # 轮换被记住
        p.assert_called_once()

    def test_double_check_reuses_other_thread_refresh(self):
        # stale_token 与内存不一致 → 判定别人已刷新，直接复用，不再打接口
        store = tk.TokenStore(access_token="fresh-at", refresh_token="rt1")
        with mock.patch.object(tk.requests, "post") as p:
            got = store.refresh_access_token("stale-at")
        self.assertEqual(got, "fresh-at")
        p.assert_not_called()

    def test_refresh_without_refresh_token_raises(self):
        store = tk.TokenStore(access_token="old-at", refresh_token="")
        with self.assertRaises(RuntimeError):
            store.refresh_access_token("old-at")

    def test_resolve_tokens_env_fallback(self):
        with mock.patch.dict(os.environ, {"IFIND_ACCESS_TOKEN": "e-at", "IFIND_REFRESH_TOKEN": "e-rt"}):
            self.assertEqual(tk.resolve_tokens("", ""), ("e-at", "e-rt"))
        self.assertEqual(tk.resolve_tokens("x", "y"), ("x", "y"))


class FileTokenStoreTests(unittest.TestCase):
    def test_seed_and_reload(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tok.json")
            tk.FileTokenStore(path, access_token="a1", refresh_token="r1")
            self.assertTrue(os.path.exists(path))  # 首次用显式 token 种子引导
            s2 = tk.FileTokenStore(path)
            self.assertEqual((s2.access_token, s2.refresh_token), ("a1", "r1"))

    def test_refresh_writes_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tok.json")
            store = tk.FileTokenStore(path, access_token="a1", refresh_token="r1")
            with mock.patch.object(tk.requests, "post", return_value=_ok_response("a2", "r1")):
                store.refresh_access_token("a1")
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["access_token"], "a2")
            # 新实例从文件读到刷新后的值
            self.assertEqual(tk.FileTokenStore(path).access_token, "a2")


if __name__ == "__main__":
    unittest.main()
