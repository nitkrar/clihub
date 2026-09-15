from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

from .config import load as load_settings
from .paths import Paths


def write_invocation(
    paths: Paths,
    namespace: str,
    tail: list[str],
    return_code: int,
    duration_ms: int,
) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "ns": namespace,
        "verb": tail[0] if tail else None,
        "argc": len(tail),
        "rc": return_code,
        "ms": duration_ms,
    }
    settings = load_settings(paths.config_file)
    if not settings.journal_enabled:
        return
    _write_line(paths.journal_file, json.dumps(payload, separators=(",", ":")), settings)


def _write_line(path: Path, line: str, settings) -> None:
    """Append, rotating first if this line would take the file over the limit.

    Hand-rolled rather than `logging.handlers`, whose import alone is a large share
    of clihub's startup and would be paid on every dispatch. `.1` is the most
    recent backup.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (line + "\n").encode("utf-8")
        if settings.journal_max_bytes > 0 and path.exists():
            if path.stat().st_size + len(data) > settings.journal_max_bytes:
                _rotate(path, settings.journal_backup_count)
        # Single append on a file opened O_APPEND: concurrent `ch` invocations
        # interleave whole lines rather than fragments.
        with path.open("ab") as handle:
            handle.write(data)
    except Exception:
        return


def _rotate(path: Path, backups: int) -> None:
    if backups < 1:
        path.unlink()
        return
    oldest = path.with_name(f"{path.name}.{backups}")
    if oldest.exists():
        oldest.unlink()
    for index in range(backups - 1, 0, -1):
        source = path.with_name(f"{path.name}.{index}")
        if source.exists():
            source.rename(path.with_name(f"{path.name}.{index + 1}"))
    path.rename(path.with_name(f"{path.name}.1"))
