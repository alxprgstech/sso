#!/usr/bin/env python3
"""
Скрипт управления версионированием ALXPRGS SSO в соответствии с требованиями VER-01..03.
Единый источник истины: файл VERSION в корне репозитория.

Использование:
    python scripts/bump_version.py check
    python scripts/bump_version.py bump patch
    python scripts/bump_version.py bump minor
    python scripts/bump_version.py bump major
    python scripts/bump_version.py bump prerelease [--rc N]
    python scripts/bump_version.py set 1.0.0-rc.1
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT_DIR / "VERSION"
CHANGELOG_FILE = ROOT_DIR / "CHANGELOG.md"
BACKEND_PYPROJECT = ROOT_DIR / "backend" / "pyproject.toml"
SDK_PYPROJECT = ROOT_DIR / "packages" / "python-sdk" / "pyproject.toml"
FRONTEND_PACKAGE_JSON = ROOT_DIR / "frontend" / "package.json"

SEMVER_REGEX = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


def read_root_version() -> str:
    if not VERSION_FILE.exists():
        raise FileNotFoundError(f"Файл {VERSION_FILE} не найден")
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not SEMVER_REGEX.match(version):
        raise ValueError(f"Недопустимый формат SemVer в {VERSION_FILE}: '{version}'")
    return version


def semver_to_pep440(version: str) -> str:
    """
    Преобразует строку SemVer в строку формата Python PEP 440.
    Например:
      1.0.0 -> 1.0.0
      1.0.0-rc.1 -> 1.0.0rc1
      1.0.0-alpha.2 -> 1.0.0a2
      1.0.0-beta.1 -> 1.0.0b1
    """
    match = SEMVER_REGEX.match(version)
    if not match:
        raise ValueError(f"Некорректная версия SemVer: {version}")

    major = match.group("major")
    minor = match.group("minor")
    patch = match.group("patch")
    prerelease = match.group("prerelease")

    base = f"{major}.{minor}.{patch}"
    if not prerelease:
        return base

    # Преобразование распространенных префиксов prerelease
    rc_match = re.match(r"^rc\.?(\d+)$", prerelease, re.IGNORECASE)
    if rc_match:
        return f"{base}rc{rc_match.group(1)}"

    alpha_match = re.match(r"^alpha\.?(\d+)$", prerelease, re.IGNORECASE)
    if alpha_match:
        return f"{base}a{alpha_match.group(1)}"

    beta_match = re.match(r"^beta\.?(\d+)$", prerelease, re.IGNORECASE)
    if beta_match:
        return f"{base}b{beta_match.group(1)}"

    # Стандартный fallback для прочих prerelease: rcN или .dev
    cleaned_pre = re.sub(r"[^a-zA-Z0-9]", "", prerelease)
    return f"{base}rc{cleaned_pre}"


def update_pyproject_version(file_path: Path, new_pep440_version: str) -> bool:
    if not file_path.exists():
        return False
    content = file_path.read_text(encoding="utf-8")
    new_content = re.sub(
        r'(?m)^version\s*=\s*["\'][^"\']+["\']',
        f'version = "{new_pep440_version}"',
        content,
    )
    if new_content != content:
        file_path.write_text(new_content, encoding="utf-8")
        return True
    return False


def update_package_json_version(file_path: Path, new_semver_version: str) -> bool:
    if not file_path.exists():
        return False
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if data.get("version") != new_semver_version:
        data["version"] = new_semver_version
        file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return True
    return False


def update_changelog(new_version: str) -> None:
    if not CHANGELOG_FILE.exists():
        return
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    content = CHANGELOG_FILE.read_text(encoding="utf-8")

    # Проверка, нет ли уже заголовка с такой версией
    if f"## [{new_version}]" in content:
        return

    unreleased_pattern = r"(## \[Unreleased\]\n)"
    replacement = f"\\1\n## [{new_version}] - {today}\n\n### Изменено\n- Выпуск версии {new_version}.\n"
    new_content = re.sub(unreleased_pattern, replacement, content)
    CHANGELOG_FILE.write_text(new_content, encoding="utf-8")


def sync_all_components(semver_version: str, update_log: bool = False) -> None:
    pep440_version = semver_to_pep440(semver_version)
    print(f"Синхронизация компонентов с версией: SemVer={semver_version}, PEP440={pep440_version}")

    VERSION_FILE.write_text(semver_version + "\n", encoding="utf-8")

    if BACKEND_PYPROJECT.exists():
        if update_pyproject_version(BACKEND_PYPROJECT, pep440_version):
            print(f"  [+] Обновлён {BACKEND_PYPROJECT.relative_to(ROOT_DIR)}")
        else:
            print(f"  [-] {BACKEND_PYPROJECT.relative_to(ROOT_DIR)} уже актуален")

    if SDK_PYPROJECT.exists():
        if update_pyproject_version(SDK_PYPROJECT, pep440_version):
            print(f"  [+] Обновлён {SDK_PYPROJECT.relative_to(ROOT_DIR)}")
        else:
            print(f"  [-] {SDK_PYPROJECT.relative_to(ROOT_DIR)} уже актуален")

    if FRONTEND_PACKAGE_JSON.exists():
        if update_package_json_version(FRONTEND_PACKAGE_JSON, semver_version):
            print(f"  [+] Обновлён {FRONTEND_PACKAGE_JSON.relative_to(ROOT_DIR)}")
        else:
            print(f"  [-] {FRONTEND_PACKAGE_JSON.relative_to(ROOT_DIR)} уже актуален")

    if update_log:
        update_changelog(semver_version)
        print("  [+] Обновлён CHANGELOG.md")


def check_consistency() -> bool:
    semver_version = read_root_version()
    pep440_version = semver_to_pep440(semver_version)
    all_ok = True
    print(f"Проверка согласованности версий (root SemVer={semver_version}, PEP440={pep440_version}):")

    if BACKEND_PYPROJECT.exists():
        content = BACKEND_PYPROJECT.read_text(encoding="utf-8")
        match = re.search(r'(?m)^version\s*=\s*["\']([^"\']+)["\']', content)
        if not match or match.group(1) != pep440_version:
            print(f"  [FAIL] {BACKEND_PYPROJECT}: ожидается '{pep440_version}', найдено '{match.group(1) if match else 'None'}'")
            all_ok = False
        else:
            print(f"  [OK] {BACKEND_PYPROJECT}")

    if SDK_PYPROJECT.exists():
        content = SDK_PYPROJECT.read_text(encoding="utf-8")
        match = re.search(r'(?m)^version\s*=\s*["\']([^"\']+)["\']', content)
        if not match or match.group(1) != pep440_version:
            print(f"  [FAIL] {SDK_PYPROJECT}: ожидается '{pep440_version}', найдено '{match.group(1) if match else 'None'}'")
            all_ok = False
        else:
            print(f"  [OK] {SDK_PYPROJECT}")

    if FRONTEND_PACKAGE_JSON.exists():
        data = json.loads(FRONTEND_PACKAGE_JSON.read_text(encoding="utf-8"))
        if data.get("version") != semver_version:
            print(f"  [FAIL] {FRONTEND_PACKAGE_JSON}: ожидается '{semver_version}', найдено '{data.get('version')}'")
            all_ok = False
        else:
            print(f"  [OK] {FRONTEND_PACKAGE_JSON}")

    if all_ok:
        print("[SUCCESS] Все существующие компоненты строго согласованы с VERSION.")
    return all_ok


def bump(part: str, rc_number: int | None = None) -> str:
    current = read_root_version()
    match = SEMVER_REGEX.match(current)
    if not match:
        raise ValueError(f"Невозможно распарсить версию {current}")

    major = int(match.group("major"))
    minor = int(match.group("minor"))
    patch = int(match.group("patch"))
    prerelease = match.group("prerelease")

    if part == "major":
        new_version = f"{major + 1}.0.0"
    elif part == "minor":
        new_version = f"{major}.{minor + 1}.0"
    elif part == "patch":
        new_version = f"{major}.{minor}.{patch + 1}"
    elif part == "prerelease":
        if prerelease and "rc." in prerelease:
            num = int(prerelease.split("rc.")[1]) + 1
        else:
            num = rc_number if rc_number is not None else 1
        new_version = f"{major}.{minor}.{patch}-rc.{num}"
    else:
        raise ValueError(f"Неизвестный тип bump: {part}")

    return new_version


def main() -> None:
    parser = argparse.ArgumentParser(description="Управление версиями ALXPRGS SSO")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check", help="Проверить согласованность версий")

    bump_parser = subparsers.add_parser("bump", help="Инкрементировать версию")
    bump_parser.add_argument("part", choices=["major", "minor", "patch", "prerelease"])
    bump_parser.add_argument("--rc", type=int, default=None, help="Номер release candidate")

    set_parser = subparsers.add_parser("set", help="Установить точную версию")
    set_parser.add_argument("version", help="Новая версия SemVer (например, 0.2.0 или 1.0.0-rc.1)")

    sync_parser = subparsers.add_parser("sync", help="Синхронизировать все компоненты с файлом VERSION")

    args = parser.parse_args()

    if args.command == "check":
        ok = check_consistency()
        sys.exit(0 if ok else 1)
    elif args.command == "sync":
        v = read_root_version()
        sync_all_components(v, update_log=False)
    elif args.command == "bump":
        new_v = bump(args.part, getattr(args, "rc", None))
        sync_all_components(new_v, update_log=True)
        print(f"Версия успешно повышена до: {new_v}")
    elif args.command == "set":
        new_v = args.version.strip()
        if not SEMVER_REGEX.match(new_v):
            print(f"Ошибка: '{new_v}' не соответствует спецификации SemVer 2.0.0", file=sys.stderr)
            sys.exit(1)
        sync_all_components(new_v, update_log=True)
        print(f"Версия успешно установлена в: {new_v}")


if __name__ == "__main__":
    main()
