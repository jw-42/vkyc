import json
import os
import urllib.request
from datetime import datetime, timezone

from vkyc.logger import get_logger

log = get_logger(__name__)

METADATA_TOKEN_URL = (
    "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token"
)
DEFAULT_MONITORING_ENDPOINT = "https://monitoring.api.cloud.yandex.net"


def emit(name: str, labels: dict[str, str], value: int = 1) -> None:
    try:
        write_point(name, labels, value)
    except Exception as exc:  # noqa: BLE001 — метрика best-effort, потеря точки некритична
        log.info("metrics.emit: не удалось записать точку %s: %s", name, exc)


def write_point(name: str, labels: dict[str, str], value: int) -> None:
    folder_id = os.environ["FOLDER_ID"]
    endpoint = os.environ.get("MONITORING_ENDPOINT", DEFAULT_MONITORING_ENDPOINT)
    stage = os.environ.get("STAGE", "")
    url = f"{endpoint}/monitoring/v2/data/write?folderId={folder_id}&service=custom"
    body = {
        "metrics": [
            {
                "name": name,
                "labels": {**labels, "stage": stage},
                "value": value,
                # ISO с микросекундной точностью — иначе Monitoring может
                # перезаписать точку в ту же секунду.
                "ts": now_iso(),
            }
        ]
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {get_iam_token()}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def get_iam_token() -> str:
    req = urllib.request.Request(METADATA_TOKEN_URL)
    req.add_header("Metadata-Flavor", "Google")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())["access_token"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
