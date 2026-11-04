"""Small shared helpers for portable, explicitly located reproduction outputs."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone


def stamp():
    return datetime.now(timezone.utc).isoformat()


def file_record(path):
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "size": path.stat().st_size, "sha256": digest.hexdigest()}


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def require_file(path, description):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{description} missing: {path}")
    return path


def require_dir(path, description):
    path = Path(path).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"{description} missing: {path}")
    return path


def new_output(path, inputs=()):
    """Never erase or silently reuse an old output, or write inside an input."""
    path = Path(path).expanduser().resolve()
    for source in inputs:
        source = Path(source).resolve()
        if path == source or source in path.parents or path in source.parents:
            raise ValueError(f"output overlaps an input: {path} and {source}")
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError(f"output must be new or empty: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_helpers(directory, *names):
    """Import the audited original modules; importing them does not launch work."""
    directory = require_dir(directory, "helper directory")
    sys.dont_write_bytecode = True
    for name in names:
        require_file(directory / (name + ".py"), name)
    sys.path.insert(0, str(directory))
    modules = [importlib.import_module(name) for name in names]
    for module in modules:
        if Path(module.__file__).resolve().parent != directory:
            raise ValueError(f"wrong helper module resolved: {module.__file__}")
    return modules


def jdk_tool(directory, name):
    directory = require_dir(directory, "JDK directory")
    suffix = ".exe" if os.name == "nt" else ""
    return require_file(directory / "bin" / (name + suffix), name)


def dependency(directory, name, aliases=()):
    directory = require_dir(directory, "dependency directory")
    for candidate in (name,) + tuple(aliases):
        path = directory / candidate
        if path.is_file():
            return path.resolve()
    raise ValueError(f"dependency missing in {directory}: {name}")


def class_records(directory):
    return [file_record(path) for path in sorted(Path(directory).rglob("*.class"))]


def clean_success(resource):
    return (resource.get("status") == "ok" and resource.get("exit_code") == 0
            and not resource.get("cleanup_error"))


@contextmanager
def environment(values):
    old = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update({key: str(value) for key, value in values.items()})
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
