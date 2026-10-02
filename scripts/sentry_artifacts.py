"""Private Debug ID bundle validation, isolated from network/upload credentials."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

DEBUG_ID = re.compile(r"//# debugId=([0-9a-f-]{36})")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_private_maps(dist: Path, private: Path, identity: dict[str, str]) -> None:
    if private.exists() and any(private.iterdir()):
        raise ValueError("Private output must be absent or empty")
    private.mkdir(parents=True, exist_ok=True)
    files = {}
    scripts = list((dist / "assets").glob("*.js"))
    if not scripts:
        raise ValueError("Frontend assets missing")
    for script in scripts:
        source_map = script.with_suffix(".js.map")
        match = DEBUG_ID.search(script.read_text(encoding="utf-8"))
        if not source_map.is_file() or not match:
            raise ValueError("Missing private map or Debug ID")
        data = json.loads(source_map.read_text(encoding="utf-8"))
        if data.get("debug_id", data.get("debugId")) != match[1]:
            raise ValueError("JS/map Debug ID mismatch")
        for path in (script, source_map):
            relative = path.relative_to(dist).as_posix()
            destination = private / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            files[relative] = {"sha256": digest(path), "debug_id": match[1]}
    (private / "manifest.json").write_text(
        json.dumps({"identity": identity, "files": files}, indent=2) + "\n", encoding="utf-8"
    )
    # The same private JS/map pair must symbolicate, not merely share an ID.
    checked = subprocess.run(
        ["node", str(Path(__file__).with_name("check_sentry_sourcemaps.mjs")), str(private)],
        capture_output=True,
        check=False,
    )
    if checked.returncode:
        raise ValueError("Private map cannot resolve the minified UI location")
    # Verified inputs only; targets are enumerated directly inside this dist.
    for path in dist.rglob("*.map"):
        path.unlink()
    (dist / "build-info.json").write_text(json.dumps(identity) + "\n", encoding="utf-8")


def verify_private_maps(private: Path, release: Path, expected_sha: str) -> dict:
    manifest = json.loads((private / "manifest.json").read_text(encoding="utf-8"))
    identity = manifest["identity"]
    release_manifest = json.loads((release / "release-manifest.json").read_text(encoding="utf-8"))
    if identity != release_manifest.get("build_identity") or identity["commit_sha"] != expected_sha:
        raise ValueError("Private/release identity mismatch")
    files = manifest["files"]
    if not files or set(files) != {
        path.relative_to(private).as_posix()
        for path in private.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }:
        raise ValueError("Private artifact set mismatch")
    for name, entry in files.items():
        if (
            not re.fullmatch(r"assets/[A-Za-z0-9_-]+\.js(?:\.map)?", name)
            or (private / name).is_symlink()
        ):
            raise ValueError("Unsafe private path")
        if digest(private / name) != entry["sha256"]:
            raise ValueError("Private integrity mismatch")
        if name.endswith(".js"):
            matched = DEBUG_ID.search((private / name).read_text(encoding="utf-8"))
            map_name = name + ".map"
            if not matched or map_name not in files or files[map_name]["debug_id"] != matched[1]:
                raise ValueError("Debug ID pair mismatch")
            source = json.loads((private / map_name).read_text(encoding="utf-8"))
            if source.get("debug_id", source.get("debugId")) != matched[1]:
                raise ValueError("Source map Debug ID mismatch")
    archive_name = f"alxprgs-sso-frontend-{identity['version']}.tar.gz"
    with tarfile.open(release / archive_name) as archive:
        members = archive.getmembers()
        if any(
            member.name.endswith(".map") or member.issym() or member.islnk() for member in members
        ):
            raise ValueError("Public map or link in frontend archive")
        deployed = {
            member.name
            for member in members
            if member.name.startswith("assets/") and member.name.endswith(".js")
        }
        if deployed != {name for name in files if name.endswith(".js")}:
            raise ValueError("Deployed JS/private bundle mismatch")
        for name in deployed:
            stream = archive.extractfile(name)
            if not stream or hashlib.sha256(stream.read()).hexdigest() != files[name]["sha256"]:
                raise ValueError("Deployed JS was rebuilt or changed")
    return manifest
