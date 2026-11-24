"""Process-scoped Windows compatibility hooks for QuantaAlpha/RD-Agent.

Python imports ``sitecustomize`` automatically.  Nothing is changed unless the
QuantaAlpha runner explicitly sets ``ASTER_WINDOWS_LINK_FALLBACK=1``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


if os.environ.get("ASTER_REDACT_LOG_SECRETS") == "1":
    # RD-Agent logs its complete LiteLLM settings object on first use.  Redact
    # credentials in both console strings and structured log objects before
    # anything can reach stdout or on-disk trace storage.
    try:
        from rdagent.log.logger import RDAgentLog

        _secret_values = tuple(
            value
            for name in (
                "OPENAI_API_KEY",
                "DEEPSEEK_API_KEY",
                "EMBEDDING_API_KEY",
                "LITELLM_API_KEY",
            )
            if (value := os.environ.get(name))
        )
        _original_info = RDAgentLog.info
        _original_log_object = RDAgentLog.log_object

        def _redact_text(value: str) -> str:
            for secret in _secret_values:
                value = value.replace(secret, "***REDACTED***")
            return value

        def _redact_object(value: Any) -> Any:
            if isinstance(value, str):
                return _redact_text(value)
            if isinstance(value, dict):
                return {key: _redact_object(item) for key, item in value.items()}
            if isinstance(value, list):
                return [_redact_object(item) for item in value]
            if isinstance(value, tuple):
                return tuple(_redact_object(item) for item in value)
            return value

        def _safe_info(self: Any, msg: str, *, tag: str = "", raw: bool = False) -> None:
            _original_info(self, _redact_text(str(msg)), tag=tag, raw=raw)

        def _safe_log_object(self: Any, obj: object, *, tag: str = "") -> None:
            _original_log_object(self, _redact_object(obj), tag=tag)

        RDAgentLog.info = _safe_info
        RDAgentLog.log_object = _safe_log_object
    except Exception:
        # Compatibility hooks must never prevent the mining process from
        # starting; the runner still clears credentials in its finally block.
        pass


if os.name == "nt" and os.environ.get("ASTER_WINDOWS_LINK_FALLBACK") == "1":
    _original_symlink_to = Path.symlink_to
    _original_unlink = Path.unlink
    _junctions: set[str] = set()

    def _key(path: Path) -> str:
        return os.path.abspath(os.fspath(path)).casefold()

    def _symlink_to(
        self: Path, target: str | os.PathLike[str], target_is_directory: bool = False
    ) -> None:
        try:
            _original_symlink_to(self, target, target_is_directory=target_is_directory)
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) != 1314:
                raise

        target_path = Path(target).resolve()
        if target_path.is_dir() or target_is_directory:
            result = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(self), str(target_path)],
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode != 0 or not self.exists():
                raise OSError(
                    f"junction fallback failed ({result.returncode}): "
                    f"{result.stdout} {result.stderr}"
                )
            _junctions.add(_key(self))
            return

        try:
            os.link(target_path, self)
        except OSError:
            shutil.copy2(target_path, self)

    def _unlink(self: Path, missing_ok: bool = False) -> None:
        key = _key(self)
        if key in _junctions:
            try:
                os.rmdir(self)
            except FileNotFoundError:
                if not missing_ok:
                    raise
            finally:
                _junctions.discard(key)
            return
        _original_unlink(self, missing_ok=missing_ok)

    Path.symlink_to = _symlink_to
    Path.unlink = _unlink
