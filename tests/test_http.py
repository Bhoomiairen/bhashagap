"""HttpClient: caching, retries, 404 handling, User-Agent."""

import pytest

from bhashagap import http as http_mod
from bhashagap.http import HttpClient


class Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers, self.url, self.text = status, body, headers or {}, "u", ""

    def json(self):
        return self._body


def make(tmp_path, responses, monkeypatch):
    client = HttpClient(tmp_path, requests_per_second=0)
    seen = []

    def fake_request(method, url, **kw):
        seen.append((method, url, kw))
        return responses.pop(0)

    monkeypatch.setattr(client.session, "request", fake_request)
    monkeypatch.setattr(http_mod.time, "sleep", lambda s: None)
    return client, seen


def test_second_call_comes_from_cache(tmp_path, monkeypatch):
    client, seen = make(tmp_path, [Resp(200, {"a": 1})], monkeypatch)
    assert client.get_json("https://x/api", params={"q": 1}) == {"a": 1}
    assert client.get_json("https://x/api", params={"q": 1}) == {"a": 1}
    assert len(seen) == 1 and client.stats == {"network": 1, "cache": 1, "errors": 0}


def test_retries_on_429_then_succeeds(tmp_path, monkeypatch):
    client, seen = make(tmp_path, [Resp(429, headers={"Retry-After": "1"}), Resp(503), Resp(200, [1])], monkeypatch)
    assert client.get_json("https://x/api") == [1]
    assert len(seen) == 3


def test_404_is_none_and_cached(tmp_path, monkeypatch):
    client, seen = make(tmp_path, [Resp(404)], monkeypatch)
    assert client.get_json("https://x/views", allow_404=True) is None
    assert client.get_json("https://x/views", allow_404=True) is None
    assert len(seen) == 1


def test_other_errors_raise(tmp_path, monkeypatch):
    client, _ = make(tmp_path, [Resp(400)], monkeypatch)
    with pytest.raises(RuntimeError):
        client.get_json("https://x/bad")


def test_offline_without_cache_raises(tmp_path):
    with pytest.raises(RuntimeError):
        HttpClient(tmp_path, offline=True).get_json("https://x/none")


def test_user_agent_set(tmp_path):
    assert "BhashaGap" in HttpClient(tmp_path).session.headers["User-Agent"]
