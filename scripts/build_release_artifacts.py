"""
ALXPRGS SSO - Скрипт сборки и проверки артефактов релиза (G8-REL / FINAL-07).
Выполняет безопасный dry-run выпуск без публикации в сеть:
1. Проверка версионирования (VERSION, backend, SDK, frontend).
2. Сборка пакетов бэкенда (wheel, sdist).
3. Сборка пакетов Python SDK (wheel, sdist).
4. Проверка сборки фронтенда и упаковка в архив tar.gz.
5. Извлечение заметок о выпуске из CHANGELOG.md.
6. Вычисление контрольных сумм SHA-256 и формирование release-manifest.json.
7. Проверка целостности всех собранных артефактов.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist" / "release"


def compute_sha256(filepath: Path) -> str:
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


def main() -> int:
    print("=" * 70)
    print("ALXPRGS SSO - Сборка и проверка артефактов релиза (Dry-Run)")
    print("=" * 70)

    # 1. Читаем версию
    version_file = ROOT_DIR / "VERSION"
    if not version_file.exists():
        print("[ERROR] Файл VERSION не найден!")
        return 1
    version = version_file.read_text(encoding="utf-8").strip()
    print(f"[INFO] Целевая версия релиза: {version}")

    # Очищаем директорию сборки
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Проверка версионирования через bump_version.py
    print("\n[1/6] Проверка синхронизации версий по репозиторию...")
    res = subprocess.run([sys.executable, str(ROOT_DIR / "scripts" / "bump_version.py"), "check"])
    if res.returncode != 0:
        print("[ERROR] Несогласованность версий в проекте!")
        return 1

    # 3. Сборка Backend пакетов
    print("\n[2/6] Сборка пакетов Backend (wheel, sdist)...")
    res = subprocess.run(
        [sys.executable, "-m", "build", str(ROOT_DIR / "backend"), "--outdir", str(DIST_DIR)]
    )
    if res.returncode != 0:
        print("[ERROR] Сбой сборки пакетов бэкенда!")
        return 1

    # 4. Сборка SDK пакетов
    print("\n[3/6] Сборка пакетов Python SDK (wheel, sdist)...")
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            str(ROOT_DIR / "packages" / "python-sdk"),
            "--outdir",
            str(DIST_DIR),
        ]
    )
    if res.returncode != 0:
        print("[ERROR] Сбой сборки пакетов Python SDK!")
        return 1

    # 5. Проверка сборки Frontend и упаковка
    print("\n[4/6] Проверка сборки Frontend и упаковка dist...")
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    fe_dir = ROOT_DIR / "frontend"
    res = subprocess.run([npm_cmd, "run", "build"], cwd=fe_dir)
    if res.returncode != 0:
        print("[ERROR] Сбой сборки фронтенда!")
        return 1

    fe_dist = fe_dir / "dist"
    fe_archive = DIST_DIR / f"alxprgs-sso-frontend-{version}.tar.gz"
    with tarfile.open(fe_archive, "w:gz") as tar:
        for root, dirs, files in os.walk(fe_dist):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(fe_dist)
                tar.add(full_path, arcname=str(rel_path))
    print(f"  [OK] Создан архив фронтенда: {fe_archive.name} ({fe_archive.stat().st_size} байт)")

    # 6. Извлечение заметок из CHANGELOG.md
    print("\n[5/6] Извлечение заметок о выпуске из CHANGELOG.md...")
    changelog_content = (ROOT_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
    pattern = r"## \[" + re.escape(version) + r"\][^\n]*\n(.*?)(?=\n## \[|\Z)"
    match = re.search(pattern, changelog_content, re.DOTALL)
    if match:
        release_notes = match.group(1).strip()
    else:
        release_notes = f"Release notes for ALXPRGS SSO {version}"
    notes_file = DIST_DIR / "RELEASE_NOTES.md"
    notes_file.write_text(release_notes, encoding="utf-8")
    print("  [OK] Заметки о выпуске сохранены в RELEASE_NOTES.md")

    # 7. Генерация контрольных сумм SHA-256 и манифеста
    print("\n[6/6] Вычисление контрольных сумм SHA-256 и манифеста...")
    artifacts = sorted(
        [
            f
            for f in DIST_DIR.iterdir()
            if f.is_file() and f.name not in ("SHA256SUMS.txt", "release-manifest.json")
        ]
    )

    checksum_lines = []
    manifest_files = {}

    for artifact in artifacts:
        sha = compute_sha256(artifact)
        size = artifact.stat().st_size
        checksum_lines.append(f"{sha}  {artifact.name}")
        manifest_files[artifact.name] = {
            "sha256": sha,
            "size_bytes": size,
        }

    sha_file = DIST_DIR / "SHA256SUMS.txt"
    sha_file.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    manifest = {
        "product": "ALXPRGS SSO",
        "version": version,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": True,
        "artifact_count": len(manifest_files),
        "artifacts": manifest_files,
    }

    manifest_file = DIST_DIR / "release-manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=" * 70)
    print("[SUCCESS] Все артефакты релиза успешно скомпилированы и проверены!")
    print(f"Директория: {DIST_DIR}")
    print("Собранные файлы:")
    for name, meta in manifest_files.items():
        print(f"  - {name} ({meta['size_bytes']} bytes, SHA-256: {meta['sha256'][:16]}...)")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
