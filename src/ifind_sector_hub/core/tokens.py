# -*- coding: utf-8 -*-
"""Token 生命周期管理：refresh_token 换新 access_token + 可选跨进程持久化。

- TokenStore：进程内存态（默认，等价旧实现：刷新只改本进程，重启重新引导）。
- FileTokenStore：JSON 落盘 + fcntl 文件锁。同机多消费方共用账号时刷新结果共享，
  REFRESH_TOKEN 轮换自动持久化（取代旧实现正则改写 config_local.py）。
"""

import datetime
import fcntl
import json
import os
import threading
from typing import Tuple

import requests

_GET_ACCESS_TOKEN_URL = "https://quantapi.51ifind.com/api/v1/get_access_token"


def _fetch_access_token(refresh_token: str, timeout: int = 30) -> dict:
    """用 refresh_token 换新 access_token，返回响应 data 字段（含轮换后的 refresh_token）。"""
    resp = requests.post(_GET_ACCESS_TOKEN_URL, json={"refresh_token": refresh_token}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errorcode") not in (0, None) and not data.get("data"):
        raise RuntimeError(f"刷新 access_token 失败: {data}")
    return data["data"]


class TokenStore:
    """token 存取与刷新（进程内 threading 锁双检；子类扩展持久化）。"""

    def __init__(self, access_token: str = "", refresh_token: str = ""):
        self._lock = threading.Lock()
        self._access_token = access_token or ""
        self._refresh_token = refresh_token or ""

    @property
    def access_token(self) -> str:
        return self._access_token

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    def refresh_access_token(self, stale_token: str) -> str:
        """
        刷新 access_token（client 401 重试专用）。
        :param stale_token: 调用方当前持有、刚被判 401 的 token
        :return: 可用 token；若其他线程/进程已刷新过（双检命中）直接复用，不打接口
        """
        with self._lock:
            fresh = self._load()
            if fresh["access_token"] and fresh["access_token"] != stale_token:
                return fresh["access_token"]
            if not fresh["refresh_token"]:
                raise RuntimeError("REFRESH_TOKEN 未配置，无法刷新 access_token")
            data = _fetch_access_token(fresh["refresh_token"])
            new_token = data["access_token"]
            new_refresh = data.get("refresh_token") or fresh["refresh_token"]
            effective = self._save(new_token, new_refresh, stale_token=stale_token)
            print(f"[IFIND-HUB] access_token 已刷新，有效至 {data.get('expired_time')}")
            return effective or new_token

    # 持久化钩子（默认内存态，子类覆盖）
    def _load(self) -> dict:
        return {"access_token": self._access_token, "refresh_token": self._refresh_token}

    def _save(self, access_token: str, refresh_token: str, stale_token: str = None) -> str:
        self._access_token = access_token
        self._refresh_token = refresh_token
        return access_token


class FileTokenStore(TokenStore):
    """JSON 文件持久化；写路径加 fcntl 锁做跨进程双检（与本进程锁叠加）。"""

    def __init__(self, path: str, access_token: str = "", refresh_token: str = ""):
        super().__init__(access_token, refresh_token)
        self.path = path
        if not os.path.exists(path) and (access_token or refresh_token):
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
            self._write(access_token, refresh_token)
        # 初始化即从文件同步内存（文件存在时以文件为准）
        d = self._read()
        self._access_token, self._refresh_token = d["access_token"], d["refresh_token"]

    def _read(self) -> dict:
        if not os.path.exists(self.path):
            return {"access_token": "", "refresh_token": ""}
        with open(self.path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return {"access_token": d.get("access_token", ""), "refresh_token": d.get("refresh_token", "")}

    def _write(self, access_token: str, refresh_token: str) -> None:
        payload = {"access_token": access_token, "refresh_token": refresh_token,
                   "updated_at": datetime.datetime.now().isoformat(timespec="seconds")}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

    def _load(self) -> dict:
        d = self._read()
        self._access_token, self._refresh_token = d["access_token"], d["refresh_token"]
        return d

    def _save(self, access_token: str, refresh_token: str, stale_token: str = None) -> str:
        # fcntl 锁内跨进程双检：文件 token ≠ 本次刷新的旧 token 且非空 → 别的进程
        # 刚刷过，采纳文件值；否则写入我们的刷新结果
        lock_path = self.path + ".lock"
        os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
        with open(lock_path, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                cur = self._read()
                if (stale_token and cur["access_token"]
                        and cur["access_token"] != stale_token):
                    self._access_token, self._refresh_token = (
                        cur["access_token"], cur["refresh_token"])
                    return cur["access_token"]
                self._write(access_token, refresh_token)
                self._access_token, self._refresh_token = access_token, refresh_token
                return access_token
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)


def resolve_tokens(access_token: str, refresh_token: str) -> Tuple[str, str]:
    """token 解析顺序：显式传入 > 环境变量 IFIND_ACCESS_TOKEN / IFIND_REFRESH_TOKEN。"""
    at = access_token or os.environ.get("IFIND_ACCESS_TOKEN", "")
    rt = refresh_token or os.environ.get("IFIND_REFRESH_TOKEN", "")
    return at, rt
