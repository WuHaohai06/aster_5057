"""Process-scoped Windows compatibility hooks for QuantaAlpha/RD-Agent.

Python imports ``sitecustomize`` automatically.  Nothing is changed unless the
QuantaAlpha runner explicitly sets ``ASTER_WINDOWS_LINK_FALLBACK=1``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
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

    # RD-Agent's LocalEnv wraps every command with POSIX `/bin/sh` and
    # `/usr/bin/timeout`, then rewrites PATH using `:` separators.  That is
    # correct for Linux but makes otherwise valid local factor workspaces fail
    # before their Python code runs on Windows.  Keep the patch process-scoped
    # and replace only LocalEnv's execution primitive; Docker environments are
    # untouched.
    try:
        from rdagent.utils.env import LocalEnv

        _posix_wrapper = re.compile(
            r"^/bin/sh -c '(?:timeout --kill-after=10 (?P<timeout>\d+) )?"
            r"(?P<command>.*); entry_exit_code=\$\?; exit \$entry_exit_code'$",
            re.DOTALL,
        )

        def _windows_local_run(
            self: Any,
            entry: str | None = None,
            local_path: str | None = None,
            env: dict[str, Any] | None = None,
            running_extra_volume: Any = None,
            **_: Any,
        ) -> tuple[str, int]:
            if entry is None:
                entry = self.conf.default_entry
            match = _posix_wrapper.match(entry)
            timeout = self.conf.running_timeout_period
            if match:
                entry = match.group("command")
                if match.group("timeout"):
                    timeout = int(match.group("timeout"))
            process_env = os.environ.copy()
            process_env.update(
                {str(key): str(value) for key, value in (env or {}).items()}
            )
            started = time.monotonic()
            try:
                result = subprocess.run(
                    entry,
                    cwd=str(Path(local_path).resolve()) if local_path else None,
                    env=process_env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    shell=True,
                    timeout=timeout,
                    check=False,
                )
                combined = (result.stdout or "") + (result.stderr or "")
                return combined, result.returncode
            except subprocess.TimeoutExpired as error:
                output = error.stdout or ""
                stderr = error.stderr or ""
                if isinstance(output, bytes):
                    output = output.decode("utf-8", errors="replace")
                if isinstance(stderr, bytes):
                    stderr = stderr.decode("utf-8", errors="replace")
                elapsed = time.monotonic() - started
                return (
                    f"{output}{stderr}\nLocal command timed out after {elapsed:.1f}s.",
                    124,
                )

        LocalEnv._run = _windows_local_run
    except Exception:
        pass

    # QuantaAlpha's upstream factor template performs sequential string
    # replacement.  With both ``$market_return`` and ``$return`` present, the
    # second replacement can corrupt the code inserted by the first.  Patch
    # rendered factor scripts in-process so the compatibility fix also applies
    # when the ignored vendor tree is freshly installed on another machine.
    try:
        from quantaalpha.core.template import CodeTemplate

        _original_template_render = CodeTemplate.render
        _unsafe_binding = """    # replace '$var' by 'df['var'] to extract var's actual values
    for col in df.columns:
        expr = expr.replace(col[1:], f\"df[\\'{col}\\']\")
"""
        _safe_binding = """    # Bind overlapping source names in one regex pass.
    source_columns = [col for col in df.columns if col.startswith('$')]
    source_map = {col[1:]: f\"df[\\'{col}\\']\" for col in source_columns}
    source_pattern = re.compile(
        r\"(?<![A-Za-z0-9_])(\" + \"|\".join(
            re.escape(token) for token in sorted(source_map, key=len, reverse=True)
        ) + r\")(?![A-Za-z0-9_])\"
    )
    expr = source_pattern.sub(lambda match: source_map[match.group(1)], expr)
"""

        def _safe_template_render(self: Any, *args: Any, **kwargs: Any) -> str:
            rendered = _original_template_render(self, *args, **kwargs)
            if _unsafe_binding not in rendered:
                return rendered
            if "import re\n" not in rendered:
                rendered = rendered.replace("import os\n", "import os\nimport re\n", 1)
            return rendered.replace(_unsafe_binding, _safe_binding)

        CodeTemplate.render = _safe_template_render
    except Exception:
        pass
