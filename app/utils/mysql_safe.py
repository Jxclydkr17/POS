# app/utils/mysql_safe.py
"""
Utilidades para ejecutar comandos MySQL CLI sin exponer la contraseña
en la lista de procesos del sistema operativo.

PROBLEMA:
  subprocess.run(["mysqldump", "--password=secreto", ...]) hace que
  cualquier usuario del SO pueda ver "secreto" con `ps aux`.

SOLUCIÓN:
  Usar --defaults-extra-file con un archivo temporal con permisos 600
  que contiene las credenciales. MySQL lee el archivo y lo cierra
  inmediatamente. El archivo se elimina después del comando.

USO:
    from app.utils.mysql_safe import build_mysql_cmd, build_mysqldump_cmd

    cmd, cleanup = build_mysqldump_cmd(host, port, user, password, db_name,
                                        extra_args=["--single-transaction"])
    try:
        result = subprocess.run(cmd, ...)
    finally:
        cleanup()  # Elimina el archivo temporal de credenciales
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from typing import Callable


def _create_defaults_file(host: str, port: int, user: str, password: str) -> Path:
    """
    Crea un archivo temporal con credenciales MySQL en formato .cnf.
    El archivo tiene permisos 600 (solo lectura/escritura para el dueño).
    """
    content = (
        "[client]\n"
        f"host={host}\n"
        f"port={port}\n"
        f"user={user}\n"
        f"password={password}\n"
    )

    fd, path = tempfile.mkstemp(prefix="vp_my_", suffix=".cnf")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        # Restringir permisos: solo el dueño puede leer/escribir
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        os.close(fd) if not os.get_inheritable(fd) else None
        os.unlink(path)
        raise

    return Path(path)


def build_mysqldump_cmd(
    host: str,
    port: int,
    user: str,
    password: str,
    db_name: str,
    extra_args: list[str] | None = None,
    mysqldump_path: str = "mysqldump",
) -> tuple[list[str], Callable]:
    """
    Construye el comando mysqldump con credenciales seguras.

    Returns:
        (cmd, cleanup_fn) — cmd es la lista de args para subprocess.run,
        cleanup_fn es una función que elimina el archivo temporal.
        SIEMPRE llamar cleanup_fn en un bloque finally.
    """
    defaults_file = _create_defaults_file(host, port, user, password)

    cmd = [
        mysqldump_path,
        f"--defaults-extra-file={defaults_file}",
        *(extra_args or []),
        db_name,
    ]

    def cleanup():
        try:
            defaults_file.unlink(missing_ok=True)
        except Exception:
            pass

    return cmd, cleanup


def build_mysql_cmd(
    host: str,
    port: int,
    user: str,
    password: str,
    db_name: str,
    mysql_path: str = "mysql",
) -> tuple[list[str], Callable]:
    """
    Construye el comando mysql CLI con credenciales seguras.

    Returns:
        (cmd, cleanup_fn) — igual que build_mysqldump_cmd.
    """
    defaults_file = _create_defaults_file(host, port, user, password)

    cmd = [
        mysql_path,
        f"--defaults-extra-file={defaults_file}",
        db_name,
    ]

    def cleanup():
        try:
            defaults_file.unlink(missing_ok=True)
        except Exception:
            pass

    return cmd, cleanup