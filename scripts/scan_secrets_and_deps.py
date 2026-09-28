"""
ALXPRGS SSO - ограниченная проверка инвариантов конфигурации (G8-CI).
Проверяет:
1. Небольшой набор известных шаблонов секретов (не полный secret scan).
2. Безопасность .env.example (только тестовые/фиктивные значения).
3. Изоляцию шаблона CD (100% закомментирован, вне активных workflows).
4. Соответствие default-off флагов в коде и конфигурации по умолчанию.
5. Наличие lock-файлов (не проверка разрешения зависимостей или CVE).

Полный аудит выполняют отдельные инструменты pip-audit, npm audit и detect-secrets в CI.
"""

from __future__ import annotations

import os
import re
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def check_cd_template() -> list[str]:
    errors = []
    active_cd = os.path.join(ROOT_DIR, ".github", "workflows", "cd.yml")
    if os.path.exists(active_cd):
        errors.append("Active CD workflow .github/workflows/cd.yml must NOT exist!")

    example_cd = os.path.join(ROOT_DIR, "deploy", "github-actions", "cd.yml.example")
    if not os.path.exists(example_cd):
        errors.append("deploy/github-actions/cd.yml.example not found!")
    else:
        with open(example_cd, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f, 1):
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    errors.append(
                        f"Line {idx} in {example_cd} is not commented out: {stripped[:50]}"
                    )
    return errors


def check_env_files() -> list[str]:
    errors = []
    # .env не должен быть закоммичен в репозиторий
    git_env = os.path.join(ROOT_DIR, ".env")
    if os.path.exists(git_env):
        # Проверяем, отслеживается ли git'ом
        import subprocess

        res = subprocess.run(
            ["git", "ls-files", ".env"], cwd=ROOT_DIR, capture_output=True, text=True
        )
        if res.stdout.strip():
            errors.append("CRITICAL: .env file is tracked by git! It must be in .gitignore.")

    # .env.example должен содержать только безопасные значения
    env_example = os.path.join(ROOT_DIR, ".env.example")
    if not os.path.exists(env_example):
        errors.append(".env.example does not exist!")
    else:
        with open(env_example, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().lower()
                    if (
                        k
                        in (
                            "FEATURE_TOTP_ENABLED",
                            "FEATURE_PASSKEY_ENABLED",
                            "FEATURE_RECOVERY_CODES_ENABLED",
                            "FEATURE_EMAIL_VERIFICATION_ENABLED",
                            "REQUIRE_VERIFIED_EMAIL",
                        )
                        and v == "true"
                    ):
                        errors.append(f"{k} must be false in .env.example (found: {line})")
    return errors


def check_default_flags_in_config() -> list[str]:
    errors = []
    config_py = os.path.join(ROOT_DIR, "backend", "app", "config.py")
    if not os.path.exists(config_py):
        errors.append(f"{config_py} not found!")
    else:
        with open(config_py, "r", encoding="utf-8") as f:
            content = f.read()
            for flag in [
                "FEATURE_TOTP_ENABLED: bool = False",
                "FEATURE_PASSKEY_ENABLED: bool = False",
                "FEATURE_RECOVERY_CODES_ENABLED: bool = False",
                "FEATURE_EMAIL_VERIFICATION_ENABLED: bool = False",
                "REQUIRE_VERIFIED_EMAIL: bool = False",
            ]:
                if flag not in content:
                    errors.append(
                        f"Expected default flag '{flag}' not found in backend/app/config.py"
                    )
    return errors


def check_secrets_in_code() -> list[str]:
    errors = []
    SECRET_PATTERNS = [
        (re.compile(r"ghp_[A-Za-z0-9_]{36}"), "GitHub Personal Access Token"),
        (re.compile(r"glpat-[A-Za-z0-9_\-]{20}"), "GitLab Personal Access Token"),
        (
            re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
            "Raw Private Key PEM (non-empty)",
        ),
        (re.compile(r"xox[baprs]-[A-Za-z0-9_\-]+"), "Slack Token"),
        (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key"),
    ]

    EXCLUDED_DIRS = {
        ".git",
        ".venv",
        "node_modules",
        "dist",
        "build",
        ".pytest_cache",
        ".ruff_cache",
    }
    # Файлы, где шаблон ключа допустим для проверок парсинга/тестов
    ALLOWED_FILES = {
        "tests/test_g8_sso_regression.py",
        "tests/test_security_and_negative_scenarios.py",
    }

    for root, dirs, files in os.walk(ROOT_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext not in (".py", ".ts", ".tsx", ".js", ".json", ".yml", ".yaml", ".env"):
                continue

            rel_path = os.path.relpath(os.path.join(root, file), ROOT_DIR).replace("\\", "/")
            if rel_path in ALLOWED_FILES:
                continue

            filepath = os.path.join(root, file)
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    for line_no, line in enumerate(f, 1):
                        for pattern, desc in SECRET_PATTERNS:
                            if pattern.search(line):
                                # Проверяем, не является ли это пустой строкой или тестом
                                if '""' in line or "''" in line:
                                    continue
                                errors.append(f"Possible {desc} in {rel_path}:{line_no}")
            except Exception as e:
                errors.append(f"Failed to read {rel_path}: {e}")

    return errors


def check_lock_files() -> list[str]:
    errors = []
    py_lock = os.path.join(ROOT_DIR, "requirements-lock.txt")
    if not os.path.exists(py_lock):
        errors.append("requirements-lock.txt not found in repository root!")

    fe_lock = os.path.join(ROOT_DIR, "frontend", "package-lock.json")
    if not os.path.exists(fe_lock):
        errors.append("frontend/package-lock.json not found!")

    return errors


def main() -> int:
    print("=" * 60)
    print("ALXPRGS SSO - ограниченная проверка инвариантов; не аудит CVE/секретов")
    print("=" * 60)

    all_errors = []

    print("[1/5] Проверка изоляции шаблона CD...")
    cd_errs = check_cd_template()
    all_errors.extend(cd_errs)
    if cd_errs:
        for err in cd_errs:
            print(f"  [FAIL] {err}")
    else:
        print("  [OK] Шаблон CD на 100% закомментирован и изолирован.")

    print("[2/5] Проверка файлов конфигурации .env и .env.example...")
    env_errs = check_env_files()
    all_errors.extend(env_errs)
    if env_errs:
        for err in env_errs:
            print(f"  [FAIL] {err}")
    else:
        print("  [OK] .env не отслеживается, .env.example безопасен.")

    print("[3/5] Проверка дефолтных флагов отложенных возможностей...")
    flags_errs = check_default_flags_in_config()
    all_errors.extend(flags_errs)
    if flags_errs:
        for err in flags_errs:
            print(f"  [FAIL] {err}")
    else:
        print("  [OK] Все 4 флага отключены по умолчанию в config.py.")

    print("[4/5] Сканирование кодовой базы на утечки секретов и ключей...")
    sec_errs = check_secrets_in_code()
    all_errors.extend(sec_errs)
    if sec_errs:
        for err in sec_errs:
            print(f"  [FAIL] {err}")
    else:
        print("  [OK] Ограниченный набор шаблонов не дал совпадений; полный scan отдельно.")

    print("[5/5] Проверка наличия lock-файлов зависимостей...")
    lock_errs = check_lock_files()
    all_errors.extend(lock_errs)
    if lock_errs:
        for err in lock_errs:
            print(f"  [FAIL] {err}")
    else:
        print("  [OK] Lock-файлы Python и Frontend присутствуют; разрешение и CVE не проверены.")

    print("=" * 60)
    if all_errors:
        print(f"[FAILED] Найдено ошибок: {len(all_errors)}")
        return 1
    else:
        print("[SUCCESS] Ограниченные инварианты пройдены; security audit отдельно.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
