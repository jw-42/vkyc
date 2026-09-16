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
