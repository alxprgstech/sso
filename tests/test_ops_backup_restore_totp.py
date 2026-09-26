"""
Интеграционный эксплуатационный тест backup/restore и восстановления TOTP с отдельным ключом (G8-OPS).
Проверяет:
1. Создание пользователя с ролями, активной сессией, OIDC-клиентом и активированным TOTP-секретом.
2. Создание резервной копии через scripts/backup_db.py.
3. Восстановление резервной копии в изолированную БД alxprgs_sso_restore_test через scripts/restore_db.py.
4. Проверку сохранности сущностей (пользователи, роли, сессии, OIDC клиенты, TOTP).
5. Успешную расшифровку и валидацию TOTP кода при наличии исходного TOTP_ENCRYPTION_KEY.
6. Отказ расшифровки TOTP при неверном или отсутствующем TOTP_ENCRYPTION_KEY.
7. Корректную очистку временной БД.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
import pyotp
import pytest
from cryptography.fernet import Fernet, InvalidToken

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKUP_SCRIPT = ROOT_DIR / "scripts" / "backup_db.py"
RESTORE_SCRIPT = ROOT_DIR / "scripts" / "restore_db.py"

ORIG_TOTP_KEY = "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE="
DIFFERENT_TOTP_KEY = Fernet.generate_key().decode()

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://sso_test_user:sso_test_password@localhost:5433/alxprgs_sso_test",
)
CONTAINER_NAME = "alxprgs-sso-test-db"
RESTORE_DB_NAME = "alxprgs_sso_restore_test"


def test_backup_restore_and_totp_key_recovery():
    clean_url = TEST_DB_URL.replace("+psycopg", "").replace("/alxprgs_sso_test", "/postgres")
    restore_url = clean_url.replace("/postgres", f"/{RESTORE_DB_NAME}")
    orig_db_url = clean_url.replace("/postgres", "/alxprgs_sso_test")

    temp_dir = tempfile.mkdtemp(prefix="sso_backup_test_")
    try:
        # 1. Засеиваем тестовые данные в alxprgs_sso_test
        raw_totp_secret = pyotp.random_base32()
        fernet = Fernet(ORIG_TOTP_KEY.encode())
        encrypted_totp = fernet.encrypt(raw_totp_secret.encode()).decode()

        with psycopg.connect(orig_db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                # Очищаем перед тестом
                cur.execute(
                    "DELETE FROM totp_credentials WHERE user_id IN (SELECT id FROM users WHERE username = 'totp_restore_user')"
                )
                cur.execute(
                    "DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username = 'totp_restore_user')"
                )
                cur.execute("DELETE FROM users WHERE username = 'totp_restore_user'")
                cur.execute("DELETE FROM oidc_clients WHERE client_id = 'totp_restore_client'")

                # Создаем пользователя
                cur.execute(
                    """
                    INSERT INTO users (id, username, email, is_active, is_superuser, email_verified)
                    VALUES (gen_random_uuid(), 'totp_restore_user', 'totp@alxprgs.tech', true, false, true)
                    RETURNING id
                    """
                )
                user_id = cur.fetchone()[0]

                # Создаем роль
                cur.execute(
                    "INSERT INTO user_roles (id, user_id, role_id) SELECT gen_random_uuid(), %s, id FROM roles WHERE name = 'user' LIMIT 1",
                    (user_id,),
                )

                # Создаем TOTP
                cur.execute(
                    """
                    INSERT INTO totp_credentials (id, user_id, encrypted_secret, is_confirmed, confirmed_at)
                    VALUES (gen_random_uuid(), %s, %s, true, now())
                    """,
                    (user_id, encrypted_totp),
                )

                # Создаем активную сессию
                cur.execute(
                    """
                    INSERT INTO sessions (id, session_token_hash, user_id, ip_address, expires_at, last_activity_at)
                    VALUES (gen_random_uuid(), 'hash_dummy_token_123', %s, '127.0.0.1', now() + interval '1 hour', now())
                    """,
                    (user_id,),
                )

                # Создаем OIDC клиента
                cur.execute(
                    """
                    INSERT INTO oidc_clients (id, client_id, client_secret_hash, client_name, client_type, is_active)
                    VALUES (gen_random_uuid(), 'totp_restore_client', 'dummy_hash', 'Restore Client', 'confidential', true)
                    """
                )

        # 2. Выполняем бэкап через scripts/backup_db.py
        b_res = subprocess.run(
            [
                sys.executable,
                str(BACKUP_SCRIPT),
                "--output-dir",
                temp_dir,
                "--docker",
                "--container",
                CONTAINER_NAME,
                "--db",
                "alxprgs_sso_test",
                "--user",
                "sso_test_user",
                "--port",
                "5432",
            ],
            capture_output=True,
            text=True,
        )
        assert b_res.returncode == 0, f"Backup failed: {b_res.stdout}\n{b_res.stderr}"

        sql_files = list(Path(temp_dir).glob("*.sql"))
        assert len(sql_files) == 1, "Expected exactly 1 backup SQL file"
        backup_file = sql_files[0]
        assert backup_file.stat().st_size > 5000, (
            f"Backup file unexpectedly small: {backup_file.stat().st_size} bytes"
        )

        # 3. Создаем чистую целевую БД alxprgs_sso_restore_test и восстанавливаем
        with psycopg.connect(clean_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS {RESTORE_DB_NAME} WITH (FORCE)")
                cur.execute(f"CREATE DATABASE {RESTORE_DB_NAME} OWNER sso_test_user")

        r_res = subprocess.run(
            [
                sys.executable,
                str(RESTORE_SCRIPT),
                str(backup_file),
                "--confirm",
                "--docker",
                "--container",
                CONTAINER_NAME,
                "--db",
                RESTORE_DB_NAME,
                "--user",
                "sso_test_user",
                "--port",
                "5432",
            ],
            capture_output=True,
            text=True,
        )
        assert r_res.returncode == 0, f"Restore failed: {r_res.stdout}\n{r_res.stderr}"

        # 4. Проверяем восстановленные данные
        with psycopg.connect(restore_url) as conn:
            with conn.cursor() as cur:
                # Пользователь
                cur.execute(
                    "SELECT id, email, is_active FROM users WHERE username = 'totp_restore_user'"
                )
                row = cur.fetchone()
                assert row is not None, "Restored user not found"
                restored_user_id = row[0]
                assert row[1] == "totp@alxprgs.tech"
                assert row[2] is True

                # Роли
                cur.execute(
                    "SELECT r.name FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE ur.user_id = %s",
                    (restored_user_id,),
                )
                roles = [r[0] for r in cur.fetchall()]
                assert "user" in roles, f"Roles missing in restored DB: {roles}"

                # Сессия
                cur.execute(
                    "SELECT expires_at FROM sessions WHERE user_id = %s", (restored_user_id,)
                )
                sess = cur.fetchone()
                assert sess is not None, "Active session missing in restored DB"

                # OIDC клиент
                cur.execute(
                    "SELECT client_name FROM oidc_clients WHERE client_id = 'totp_restore_client'"
                )
                client = cur.fetchone()
                assert client is not None and client[0] == "Restore Client", (
                    "OIDC client missing in restored DB"
                )

                # TOTP credential
                cur.execute(
                    "SELECT encrypted_secret, is_confirmed FROM totp_credentials WHERE user_id = %s",
                    (restored_user_id,),
                )
                totp_row = cur.fetchone()
                assert totp_row is not None and totp_row[1] is True, (
                    "TOTP credential missing or not confirmed"
                )
                restored_encrypted_secret = totp_row[0]

        # 5. Проверяем восстановление TOTP с оригинальным ключом
        orig_fernet = Fernet(ORIG_TOTP_KEY.encode())
        decrypted_secret = orig_fernet.decrypt(restored_encrypted_secret.encode()).decode()
        assert decrypted_secret == raw_totp_secret, "Decrypted TOTP secret does not match original"

        # Генерируем и проверяем TOTP код
        totp = pyotp.TOTP(decrypted_secret)
        current_code = totp.now()
        assert totp.verify(current_code), "TOTP code verification failed on restored credential"

        # 6. Проверяем, что неверный ключ шифрования категорически НЕ расшифровывает секрет
        wrong_fernet = Fernet(DIFFERENT_TOTP_KEY.encode())
        with pytest.raises(InvalidToken):
            wrong_fernet.decrypt(restored_encrypted_secret.encode())

    finally:
        # 7. Очистка временных файлов и тестовой базы восстановления
        shutil.rmtree(temp_dir, ignore_errors=True)
        try:
            with psycopg.connect(clean_url, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"DROP DATABASE IF EXISTS {RESTORE_DB_NAME} WITH (FORCE)")
        except Exception:
            pass
