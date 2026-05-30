"""
Tests de configuración del motor de base de datos (FASE 3.3).

Blindan dos arreglos:
  1. El motor se resuelve desde DB_ENGINE en el .env (antes `_auto_detect_engine`
     pisaba el valor del .env vía os.environ y la app quedaba clavada en sqlite).
  2. Un DB_PORT vacío en el .env no debe abortar el arranque (validador que
     lo convierte al default 3306). El wizard, al elegir SQLite, deja DB_PORT="".
"""
import app.core.config as cfg


# ── Validador de DB_PORT (crash fix) ──────────────────────────────────────

def test_db_port_empty_defaults_to_3306(monkeypatch):
    monkeypatch.delenv("DB_PORT", raising=False)
    s = cfg.Settings(_env_file=None, db_port="")
    assert s.db_port == 3306


def test_db_port_blank_defaults_to_3306():
    s = cfg.Settings(_env_file=None, db_port="   ")
    assert s.db_port == 3306


def test_db_port_valid_value_kept():
    s = cfg.Settings(_env_file=None, db_port="5000")
    assert s.db_port == 5000


# ── Validador de DB_ENGINE ────────────────────────────────────────────────

def test_db_engine_normalized_lowercase():
    assert cfg.Settings(_env_file=None, db_engine="MYSQL").db_engine == "mysql"


def test_db_engine_invalid_rejected():
    import pytest
    with pytest.raises(Exception):
        cfg.Settings(_env_file=None, db_engine="postgres")


# ── Resolución del motor desde el .env ────────────────────────────────────

def test_engine_mysql_from_env_file(tmp_path, monkeypatch):
    for k in ("DB_ENGINE", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_NAME"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "DB_ENGINE=mysql\nDB_USER=violette\nDB_PASSWORD=secreta\n"
        "DB_HOST=192.168.1.50\nDB_PORT=3306\nDB_NAME=violette_db\n",
        encoding="utf-8",
    )
    s = cfg.Settings(_env_file=str(env))
    assert s.db_engine == "mysql"
    assert s.db_user == "violette"
    assert s.db_host == "192.168.1.50"


def test_engine_sqlite_from_env_file(tmp_path, monkeypatch):
    for k in ("DB_ENGINE", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_NAME"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    # SQLite tal como lo deja el wizard: engine sqlite + credenciales MySQL vacías
    env.write_text(
        "DB_ENGINE=sqlite\nDB_SQLITE_PATH=violette_pos.db\n"
        "DB_USER=\nDB_PASSWORD=\nDB_HOST=\nDB_PORT=\nDB_NAME=\n",
        encoding="utf-8",
    )
    s = cfg.Settings(_env_file=str(env))
    assert s.db_engine == "sqlite"
    assert s.db_port == 3306  # DB_PORT vacío no rompe


def test_engine_defaults_sqlite_when_absent(tmp_path, monkeypatch):
    for k in ("DB_ENGINE", "DB_USER", "DB_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text("APP_NAME=ViolettePOS\n", encoding="utf-8")
    assert cfg.Settings(_env_file=str(env)).db_engine == "sqlite"


# ── Construcción de URL ───────────────────────────────────────────────────

def test_mysql_url_urlencodes_password(monkeypatch):
    s = cfg.Settings(
        _env_file=None, db_engine="mysql", db_user="violette",
        db_password="P@ss/w0rd#1", db_host="h", db_port=3306, db_name="d",
    )
    monkeypatch.setattr(cfg, "settings", s)
    url = cfg.get_database_url()
    assert url.startswith("mysql+pymysql://violette:")
    assert "P%40ss%2Fw0rd%231" in url  # @ / # url-encoded
    assert url.endswith("@h:3306/d")


def test_sqlite_url_built_from_path(monkeypatch):
    s = cfg.Settings(_env_file=None, db_engine="sqlite", db_sqlite_path="violette_pos.db")
    monkeypatch.setattr(cfg, "settings", s)
    assert cfg.get_database_url().startswith("sqlite:///")