import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from haiku_checker.web.app import create_app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    # TestClient は Host: testserver を送るため明示的に許可する
    return TestClient(create_app(allowed_hosts=["testserver"]))


def test_status_does_not_leak_keys(client):
    body = client.get("/api/status").json()
    assert body["kigo_count"] > 0
    assert isinstance(body["llm_available"], bool)
    # API キーそのものが混ざっていないこと
    assert not any("sk-" in str(v) for v in body.values())


def test_index_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "俳句チェッカー" in res.text


def test_analyze_returns_all_three_modules(client):
    res = client.post("/api/analyze", json={
        "haiku": "古池や 蛙飛びこむ 水の音",
        "use_web": False,
    })
    assert res.status_code == 200
    body = res.json()
    assert body["structure"]["pattern"] == "5・7・5"
    assert body["structure"]["is_teikei"] is True
    assert any(k["word"] == "蛙" for k in body["saijiki"]["kigo"])
    assert body["similarity"]["risk"] == "高"
    # LLM は呼ばれない
    assert "evaluation" not in body


def test_analyze_honours_yomi_and_season(client):
    res = client.post("/api/analyze", json={
        "haiku": "万緑の 中や吾子の歯 生え初むる",
        "yomi": "ばんりょくの なかやあこのは はえそむる",
        "season": "冬",
        "use_web": False,
    })
    body = res.json()
    assert body["structure"]["pattern"] == "5・7・5"
    assert body["saijiki"]["target_season"] == "冬"
    assert "万緑" in body["saijiki"]["out_of_season"]


def test_invalid_season_rejected(client):
    res = client.post("/api/analyze", json={"haiku": "古池や", "season": "梅雨"})
    assert res.status_code == 400


def test_invalid_date_rejected(client):
    res = client.post("/api/analyze", json={"haiku": "古池や", "date": "2026/07/01"})
    assert res.status_code == 400


def test_empty_haiku_rejected(client):
    res = client.post("/api/analyze", json={"haiku": ""})
    assert res.status_code == 422


def test_kigo_search(client):
    body = client.get("/api/kigo", params={"season": "新年", "category": "行事"}).json()
    assert body["total"] >= 5
    assert all(i["season"] == "新年" for i in body["items"])

    body2 = client.get("/api/kigo", params={"q": "月"}).json()
    assert any(i["word"] == "名月" for i in body2["items"])


def test_evaluate_reports_missing_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    res = client.post("/api/evaluate", json={"haiku": "古池や 蛙飛びこむ 水の音", "use_web": False})
    # キーが無い場合はエラーではなく、理由付きの未実行として返る
    assert res.status_code == 200
    body = res.json()
    assert body["available"] is False
    assert "ANTHROPIC_API_KEY" in body["error"]


def test_evaluate_rejects_bad_effort(client):
    res = client.post("/api/evaluate", json={"haiku": "古池や", "effort": "turbo"})
    assert res.status_code == 400


def test_foreign_host_header_rejected():
    """DNS リバインディング経路を塞げているか。

    悪意あるサイトが自分のドメインを 127.0.0.1 に解決させると同一オリジン扱いになり、
    ブラウザを踏んだだけで /api/evaluate を叩かれて API 課金が発生しうる。
    Host ヘッダを検証することでこれを拒否する。
    """
    c = TestClient(create_app(allowed_hosts=["localhost", "127.0.0.1"]))
    ok = c.post("/api/analyze", json={"haiku": "古池や", "use_web": False},
                headers={"Host": "127.0.0.1"})
    assert ok.status_code == 200

    bad = c.post("/api/analyze", json={"haiku": "古池や", "use_web": False},
                 headers={"Host": "evil.example"})
    assert bad.status_code == 400


def test_allowed_hosts_from_env(monkeypatch):
    from haiku_checker.web.app import resolve_allowed_hosts

    monkeypatch.delenv("HAIKU_ALLOWED_HOSTS", raising=False)
    assert resolve_allowed_hosts() == ["localhost", "127.0.0.1", "::1"]

    monkeypatch.setenv("HAIKU_ALLOWED_HOSTS", "haiku.local, 192.168.1.5")
    assert resolve_allowed_hosts() == ["haiku.local", "192.168.1.5"]

    # 引数は環境変数より優先される
    assert resolve_allowed_hosts(["only.example"]) == ["only.example"]


def test_no_cors_headers_exposed(client):
    """CORS を開けていないこと。開けると任意サイトの JS が応答を読めてしまう。"""
    res = client.post("/api/analyze",
                      json={"haiku": "古池や", "use_web": False},
                      headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in res.headers}
