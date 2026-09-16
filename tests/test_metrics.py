import vkyc.metrics as metrics


def test_emit_never_raises(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(metrics, "write_point", boom)
    metrics.emit("some.metric", {"label": "x"})  # не должно бросить


def test_write_point_calls_urlopen_with_token(monkeypatch):
    monkeypatch.setenv("FOLDER_ID", "folder1")
    monkeypatch.setattr(metrics, "get_iam_token", lambda: "tok123")

    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout=10):
        calls.append(req)
        return FakeResponse()

    monkeypatch.setattr(metrics.urllib.request, "urlopen", fake_urlopen)

    metrics.write_point("m", {"label": "x"}, 1)

    assert len(calls) == 1
    assert calls[0].get_header("Authorization") == "Bearer tok123"


def test_now_iso_is_isoformat():
    value = metrics.now_iso()
    assert "T" in value


class FakeResponse:
    def __init__(self, body=b"{}"):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def _mock_transport(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        if req.full_url == metrics.METADATA_TOKEN_URL:
            import json as _json
            return FakeResponse(_json.dumps({"access_token": "t"}).encode())
        return FakeResponse()

    monkeypatch.setattr(metrics.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_emit_merges_caller_labels_and_keeps_stage(monkeypatch):
    monkeypatch.setenv("FOLDER_ID", "folder-xyz")
    monkeypatch.setenv("STAGE", "dev")
    calls = _mock_transport(monkeypatch)

    metrics.emit("some.metric", {"channel": "email"})

    body = __import__("json").loads(calls[-1].data)
    assert body["metrics"][0]["labels"] == {"channel": "email", "stage": "dev"}


def test_emit_uses_endpoint_override(monkeypatch):
    monkeypatch.setenv("FOLDER_ID", "folder-xyz")
    monkeypatch.setenv("MONITORING_ENDPOINT", "https://mon.example")
    calls = _mock_transport(monkeypatch)

    metrics.emit("some.metric", {})

    assert calls[-1].full_url.startswith("https://mon.example/monitoring/v2/data/write")


def test_emit_never_raises_when_folder_id_missing(monkeypatch):
    monkeypatch.delenv("FOLDER_ID", raising=False)
    _mock_transport(monkeypatch)

    metrics.emit("some.metric", {})
