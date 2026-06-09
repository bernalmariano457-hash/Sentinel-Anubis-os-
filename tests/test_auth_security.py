from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# FIXTURES COMPARTIDOS
@pytest.fixture()
def security_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data" / "security"
    d.mkdir(parents=True)
    return d


@pytest.fixture()
def mock_sentinel() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def mock_console() -> MagicMock:
    c = MagicMock()
    c.print = MagicMock()
    return c


@pytest.fixture()
def mock_log() -> MagicMock:
    log = MagicMock()
    for m in ("info", "warning", "error", "success", "audit"):
        setattr(log, m, MagicMock())
    return log


# BLOQUE 1 — FUNCIONES DE HASHING (core.auth)
class TestHashFunctions:

    def test_hash_bcrypt_devuelve_prefijo_correcto(self):
        from core.auth import _hash_bcrypt
        h = _hash_bcrypt("password123")
        assert h.startswith("$2"), "bcrypt debe empezar con $2b$ o $2a$"

    def test_hash_sha256_salted_tiene_prefijo_y_tres_partes(self):
        from core.auth import _hash_sha256_salted
        h = _hash_sha256_salted("password123")
        partes = h.split(":")
        assert partes[0] == "sha256s"
        assert len(partes) == 3
        assert len(
            partes[1]) == 32, "La sal debe ser 16 bytes en hex = 32 chars"

    def test_hash_rechaza_password_corta(self):
        from core.auth import _hash
        with pytest.raises(ValueError, match="8 caracteres"):
            _hash("corta")

    def test_hash_acepta_password_minima(self):
        from core.auth import _hash
        h = _hash("12345678")
        assert h  # no lanza excepción

    def test_dos_hashes_del_mismo_password_son_distintos(self):
        """La sal garantiza que el mismo input produce hashes distintos."""
        from core.auth import _hash
        h1 = _hash("mismapassword1")
        h2 = _hash("mismapassword1")
        assert h1 != h2


class TestVerificar:

    def test_verifica_hash_bcrypt_correcto(self):
        from core.auth import _hash_bcrypt, _verificar
        h = _hash_bcrypt("correcta123")
        assert _verificar("correcta123", h) is True

    def test_rechaza_password_incorrecta_bcrypt(self):
        from core.auth import _hash_bcrypt, _verificar
        h = _hash_bcrypt("correcta123")
        assert _verificar("incorrecta123", h) is False

    def test_verifica_sha256_salted(self):
        from core.auth import _hash_sha256_salted, _verificar
        h = _hash_sha256_salted("mi_password_1")
        assert _verificar("mi_password_1", h) is True

    def test_rechaza_password_incorrecta_sha256_salted(self):
        from core.auth import _hash_sha256_salted, _verificar
        h = _hash_sha256_salted("mi_password_1")
        assert _verificar("otra_password_1", h) is False

    def test_verifica_hash_legacy_sin_sal(self):
        """Hash SHA-256 plano de 64 hex chars — formato legacy."""
        from core.auth import _verificar
        legacy = hashlib.sha256("legacy_pass1".encode()).hexdigest()
        assert _verificar("legacy_pass1", legacy) is True

    def test_rechaza_hash_legacy_incorrecto(self):
        from core.auth import _verificar
        legacy = hashlib.sha256("legacy_pass1".encode()).hexdigest()
        assert _verificar("otra_pass", legacy) is False

    def test_verifica_devuelve_false_con_hash_vacio(self):
        from core.auth import _verificar
        assert _verificar("cualquier_cosa", "") is False

    def test_verifica_devuelve_false_con_hash_invalido(self):
        from core.auth import _verificar
        assert _verificar("cualquier_cosa",
                          "esto_no_es_un_hash_valido") is False


class TestEsLegacy:

    def test_sha256_plano_es_legacy(self):
        from core.auth import _es_legacy
        legacy = hashlib.sha256("pass12345".encode()).hexdigest()
        assert _es_legacy(legacy) is True

    def test_sha256_salted_es_legacy(self):
        from core.auth import _es_legacy, _hash_sha256_salted
        h = _hash_sha256_salted("pass12345")
        assert _es_legacy(h) is True

    def test_bcrypt_no_es_legacy(self):
        from core.auth import _es_legacy, _hash_bcrypt
        h = _hash_bcrypt("pass12345")
        assert _es_legacy(h) is False


# BLOQUE 2 — LOCKOUT MANAGER
class TestLockoutManager:

    @pytest.fixture(autouse=True)
    def _patch_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Redirige _LOCKOUT_FILE al directorio temporal."""
        import core.auth as auth_mod
        lockout_file = tmp_path / ".lockout"
        monkeypatch.setattr(auth_mod, "_LOCKOUT_FILE", lockout_file)
        monkeypatch.setattr(auth_mod, "_MAX_INTENTOS", 3)
        monkeypatch.setattr(auth_mod, "_VENTANA_SEG", 300)

    def test_no_bloqueado_inicialmente(self):
        from core.auth import _LockoutManager
        lm = _LockoutManager()
        bloqueado, restante = lm.esta_bloqueado()
        assert bloqueado is False
        assert restante == 0

    def test_registrar_un_fallo_no_bloquea(self):
        from core.auth import _LockoutManager
        lm = _LockoutManager()
        lm.registrar_fallo()
        bloqueado, _ = lm.esta_bloqueado()
        assert bloqueado is False

    def test_tres_fallos_bloquean_el_sistema(self):
        from core.auth import _LockoutManager
        lm = _LockoutManager()
        lm.registrar_fallo()
        lm.registrar_fallo()
        lm.registrar_fallo()
        bloqueado, restante = lm.esta_bloqueado()
        assert bloqueado is True
        assert restante > 0

    def test_reiniciar_limpia_el_bloqueo(self):
        from core.auth import _LockoutManager
        lm = _LockoutManager()
        lm.registrar_fallo()
        lm.registrar_fallo()
        lm.registrar_fallo()
        lm.reiniciar()
        bloqueado, _ = lm.esta_bloqueado()
        assert bloqueado is False

    def test_intentos_restantes_decrece_con_fallos(self):
        from core.auth import _LockoutManager
        lm = _LockoutManager()
        assert lm.intentos_restantes() == 3
        lm.registrar_fallo()
        assert lm.intentos_restantes() == 2
        lm.registrar_fallo()
        assert lm.intentos_restantes() == 1

    def test_bloqueo_persiste_entre_instancias(self, tmp_path: Path):
        """El lockout sobrevive crear una nueva instancia (simula reinicio)."""
        import core.auth as auth_mod
        lm1 = _LockoutManager_new(auth_mod)
        lm1.registrar_fallo()
        lm1.registrar_fallo()
        lm1.registrar_fallo()

        lm2 = _LockoutManager_new(auth_mod)
        bloqueado, _ = lm2.esta_bloqueado()
        assert bloqueado is True

    def test_intentos_fuera_de_ventana_se_ignoran(self, monkeypatch):
        import core.auth as auth_mod
        lm = _LockoutManager_new(auth_mod)

        # Escribir manualmente intentos con timestamps viejos
        datos_viejos = {"intentos": [time.time() - 999], "bloqueado_hasta": 0}
        auth_mod._LOCKOUT_FILE.write_text(
            json.dumps(datos_viejos), encoding="utf-8")

        lm.registrar_fallo()
        # El intento viejo no debe contar; solo hay 1 intento válido
        assert lm.intentos_restantes() == 2


def _LockoutManager_new(auth_mod):
    return auth_mod._LockoutManager()


# BLOQUE 3 — CREDENTIAL STORE
class TestCredentialStore:

    @pytest.fixture(autouse=True)
    def _patch_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import core.auth as auth_mod
        creds_file = tmp_path / ".credentials"
        monkeypatch.setattr(auth_mod, "_CREDS_FILE", creds_file)

    def test_leer_devuelve_none_si_no_existe(self):
        from core.auth import _CredentialStore
        cs = _CredentialStore({})
        assert cs.leer() is None

    def test_escribir_y_leer_hash(self):
        from core.auth import _CredentialStore
        cs = _CredentialStore({})
        cs.escribir("mi_hash_de_prueba")
        assert cs.leer() == "mi_hash_de_prueba"

    def test_existe_false_sin_credenciales(self):
        from core.auth import _CredentialStore
        cs = _CredentialStore({})
        assert cs.existe() is False

    def test_existe_true_con_credenciales(self):
        from core.auth import _CredentialStore
        cs = _CredentialStore({})
        cs.escribir("cualquier_hash")
        assert cs.existe() is True

    def test_variable_de_entorno_tiene_prioridad(self, monkeypatch: pytest.MonkeyPatch):
        from core.auth import _CredentialStore
        monkeypatch.setenv("SENTINEL_PASSWORD_HASH", "hash_desde_env")
        cs = _CredentialStore({})
        assert cs.leer() == "hash_desde_env"

    def test_migra_hash_desde_config_json(self, tmp_path: Path):
        import core.auth as auth_mod
        config = {"sistema": {"password_hash": "hash_legacy_en_config"}}
        cs = auth_mod._CredentialStore(config)
        h = cs.leer()
        assert h == "hash_legacy_en_config"
        # Después de leer, el archivo de credenciales debe existir
        assert auth_mod._CREDS_FILE.exists()


# BLOQUE 4 — GESTOR AUTH (integración)
class TestGestorAuthCambiarPassword:

    @pytest.fixture(autouse=True)
    def _patch_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import core.auth as auth_mod
        monkeypatch.setattr(auth_mod, "_CREDS_FILE", tmp_path / ".credentials")
        monkeypatch.setattr(auth_mod, "_LOCKOUT_FILE", tmp_path / ".lockout")

    def _crear_gestor(self, mock_console, mock_log):
        from core.auth import GestorAuth, _hash
        config = {}
        ga = GestorAuth(config, mock_console, mock_log)
        # Establecer contraseña inicial directamente
        ga._creds.escribir(_hash("password_actual1"))
        return ga

    def test_cambio_exitoso_con_password_correcta(self, mock_console, mock_log):
        from core.auth import _verificar
        ga = self._crear_gestor(mock_console, mock_log)
        resultado = ga.cambiar_password("password_actual1", "nueva_password1")
        assert resultado is True
        # Verificar que la nueva contraseña funciona
        nuevo_hash = ga._creds.leer()
        assert _verificar("nueva_password1", nuevo_hash) is True

    def test_cambio_falla_con_password_incorrecta(self, mock_console, mock_log):
        ga = self._crear_gestor(mock_console, mock_log)
        resultado = ga.cambiar_password(
            "password_incorrecta", "nueva_password1")
        assert resultado is False

    def test_cambio_rechaza_nueva_password_corta(self, mock_console, mock_log):
        ga = self._crear_gestor(mock_console, mock_log)
        with pytest.raises(ValueError, match="8 caracteres"):
            ga.cambiar_password("password_actual1", "corta")


class TestMigracionBcrypt:

    @pytest.fixture(autouse=True)
    def _patch_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import core.auth as auth_mod
        monkeypatch.setattr(auth_mod, "_CREDS_FILE", tmp_path / ".credentials")
        monkeypatch.setattr(auth_mod, "_LOCKOUT_FILE", tmp_path / ".lockout")

    def test_migra_hash_legacy_a_bcrypt_tras_login(self, mock_console, mock_log):
        import core.auth as auth_mod
        from core.auth import GestorAuth

        # Guardar hash legacy (SHA-256 sin sal)
        legacy_hash = hashlib.sha256("mi_password1".encode()).hexdigest()
        auth_mod._CREDS_FILE.write_text(legacy_hash, encoding="utf-8")

        ga = GestorAuth({}, mock_console, mock_log)
        ga._migrar_hash_si_necesario("mi_password1", legacy_hash)

        nuevo_hash = auth_mod._CREDS_FILE.read_text(encoding="utf-8").strip()
        assert nuevo_hash.startswith("$2"), "Debe haberse migrado a bcrypt"

    def test_no_migra_si_ya_es_bcrypt(self, mock_console, mock_log):
        import core.auth as auth_mod
        from core.auth import GestorAuth, _hash_bcrypt

        hash_bcrypt = _hash_bcrypt("mi_password1")
        auth_mod._CREDS_FILE.write_text(hash_bcrypt, encoding="utf-8")
        mtime_antes = auth_mod._CREDS_FILE.stat().st_mtime

        ga = GestorAuth({}, mock_console, mock_log)
        ga._migrar_hash_si_necesario("mi_password1", hash_bcrypt)

        mtime_despues = auth_mod._CREDS_FILE.stat().st_mtime
        assert mtime_antes == mtime_despues, "El archivo no debe haberse modificado"


# BLOQUE 5 — SECURITY MODULE (Fernet)
class TestSecurityModuleInit:

    @pytest.fixture(autouse=True)
    def _patch_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import core.Security as sec_mod
        key_dir = tmp_path / "data" / "security"
        backup_dir = key_dir / "key_backups"
        key_dir.mkdir(parents=True)
        backup_dir.mkdir(parents=True)
        monkeypatch.setattr(sec_mod, "_KEY_DIR",    key_dir)
        monkeypatch.setattr(sec_mod, "_KEY_FILE",
                            key_dir / "anubis_master.key")
        monkeypatch.setattr(sec_mod, "_BACKUP_DIR", backup_dir)

    def test_genera_clave_si_no_existe(self, mock_sentinel, tmp_path):
        import core.Security as sec_mod
        assert not sec_mod._KEY_FILE.exists()
        from core.Security import SecurityModule
        sm = SecurityModule(mock_sentinel)
        assert sec_mod._KEY_FILE.exists()
        assert sm._fernet is not None

    def test_reutiliza_clave_existente(self, mock_sentinel):
        from core.Security import SecurityModule
        sm1 = SecurityModule(mock_sentinel)
        clave1 = sm1._fernet._signing_key

        sm2 = SecurityModule(mock_sentinel)
        clave2 = sm2._fernet._signing_key

        assert clave1 == clave2, "Debe cargar la misma clave del disco"

    def test_estado_refleja_clave_cargada(self, mock_sentinel):
        from core.Security import SecurityModule
        sm = SecurityModule(mock_sentinel)
        estado = sm.estado()
        assert estado["clave_cargada"] is True
        assert estado["clave_existe"] is True
        assert estado["backups"] == 0


class TestCifradoDatos:

    @pytest.fixture(autouse=True)
    def _patch_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import core.Security as sec_mod
        key_dir = tmp_path / "data" / "security"
        key_dir.mkdir(parents=True)
        (key_dir / "key_backups").mkdir()
        monkeypatch.setattr(sec_mod, "_KEY_DIR",    key_dir)
        monkeypatch.setattr(sec_mod, "_KEY_FILE",
                            key_dir / "anubis_master.key")
        monkeypatch.setattr(sec_mod, "_BACKUP_DIR", key_dir / "key_backups")

    @pytest.fixture()
    def sm(self, mock_sentinel) -> object:
        from core.Security import SecurityModule
        return SecurityModule(mock_sentinel)

    def test_cifrar_y_descifrar_datos(self, sm):
        datos = b"datos sensibles de prueba"
        cifrado = sm.cifrar_datos(datos)
        assert cifrado != datos
        assert sm.descifrar_datos(cifrado) == datos

    def test_datos_cifrados_son_distintos_cada_vez(self, sm):
        datos = b"mismo contenido"
        c1 = sm.cifrar_datos(datos)
        c2 = sm.cifrar_datos(datos)
        assert c1 != c2

    def test_descifrar_token_invalido_lanza_excepcion(self, sm):
        from cryptography.fernet import InvalidToken
        with pytest.raises(InvalidToken):
            sm.descifrar_datos(b"esto_no_es_un_token_valido")


class TestCifradoArchivos:

    @pytest.fixture(autouse=True)
    def _patch_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import core.Security as sec_mod
        key_dir = tmp_path / "data" / "security"
        key_dir.mkdir(parents=True)
        (key_dir / "key_backups").mkdir()
        monkeypatch.setattr(sec_mod, "_KEY_DIR",    key_dir)
        monkeypatch.setattr(sec_mod, "_KEY_FILE",
                            key_dir / "anubis_master.key")
        monkeypatch.setattr(sec_mod, "_BACKUP_DIR", key_dir / "key_backups")

    @pytest.fixture()
    def sm(self, mock_sentinel):
        from core.Security import SecurityModule
        return SecurityModule(mock_sentinel)

    @pytest.fixture()
    def archivo_prueba(self, tmp_path: Path) -> Path:
        f = tmp_path / "evidencia.txt"
        f.write_bytes(b"contenido sensible de la evidencia")
        return f

    def test_cifrar_modifica_contenido(self, sm, archivo_prueba):
        contenido_original = archivo_prueba.read_bytes()
        resultado = sm.encriptar_archivo(archivo_prueba)
        assert resultado is True
        assert archivo_prueba.read_bytes() != contenido_original

    def test_cifrar_y_descifrar_restaura_contenido(self, sm, archivo_prueba):
        contenido_original = archivo_prueba.read_bytes()
        sm.encriptar_archivo(archivo_prueba)
        sm.desencriptar_archivo(archivo_prueba)
        assert archivo_prueba.read_bytes() == contenido_original

    def test_cifrar_archivo_inexistente_devuelve_false(self, sm, tmp_path):
        resultado = sm.encriptar_archivo(tmp_path / "no_existe.txt")
        assert resultado is False

    def test_descifrar_archivo_inexistente_devuelve_false(self, sm, tmp_path):
        resultado = sm.desencriptar_archivo(tmp_path / "no_existe.txt")
        assert resultado is False

    def test_descifrar_archivo_con_datos_invalidos_devuelve_false(self, sm, tmp_path):
        f = tmp_path / "corrupto.txt"
        f.write_bytes(b"esto no esta cifrado con fernet")
        resultado = sm.desencriptar_archivo(f)
        assert resultado is False


class TestRotacionClave:

    @pytest.fixture(autouse=True)
    def _patch_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import core.Security as sec_mod
        key_dir = tmp_path / "data" / "security"
        key_dir.mkdir(parents=True)
        (key_dir / "key_backups").mkdir()
        monkeypatch.setattr(sec_mod, "_KEY_DIR",    key_dir)
        monkeypatch.setattr(sec_mod, "_KEY_FILE",
                            key_dir / "anubis_master.key")
        monkeypatch.setattr(sec_mod, "_BACKUP_DIR", key_dir / "key_backups")

    @pytest.fixture()
    def sm(self, mock_sentinel):
        from core.Security import SecurityModule
        return SecurityModule(mock_sentinel)

    def test_rotacion_genera_clave_distinta(self, sm):
        clave_antes = sm._fernet._signing_key
        sm.rotar_clave()
        assert sm._fernet._signing_key != clave_antes

    def test_rotacion_crea_backup(self, sm):
        import core.Security as sec_mod
        sm.rotar_clave()
        backups = list(sec_mod._BACKUP_DIR.glob("*.bak"))
        assert len(backups) == 1

    def test_rotacion_recifra_archivos(self, sm, tmp_path):
        archivo = tmp_path / "datos.bin"
        archivo.write_bytes(b"datos importantes")

        sm.encriptar_archivo(archivo)
        sm.rotar_clave(archivos_cifrados=[archivo])
        resultado = sm.desencriptar_archivo(archivo)

        assert resultado is True
        assert archivo.read_bytes() == b"datos importantes"

    def test_rotacion_multiples_veces_acumula_backups(self, sm):
        import core.Security as sec_mod
        timestamps = ["20260101_000001", "20260101_000002", "20260101_000003"]
        with patch("core.Security.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.side_effect = timestamps
            sm.rotar_clave()
            sm.rotar_clave()
            sm.rotar_clave()
        backups = list(sec_mod._BACKUP_DIR.glob("*.bak"))
        assert len(backups) == 3

    def test_estado_muestra_backups_correctamente(self, sm):
        timestamps = ["20260101_000001", "20260101_000002"]
        with patch("core.Security.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.side_effect = timestamps
            sm.rotar_clave()
            sm.rotar_clave()
        estado = sm.estado()
        assert estado["backups"] == 2


# BLOQUE 6 — VENDOR RESOLVER (core.vendor_resolver)
class TestVendorResolver:

    @pytest.fixture(autouse=True)
    def _limpiar_cache(self):
        from core.vendor_resolver import VendorResolver
        VendorResolver.clear_cache()
        yield
        VendorResolver.clear_cache()

    def test_resuelve_mac_apple_conocida(self):
        from core.vendor_resolver import VendorResolver
        assert VendorResolver.resolve("8C:64:A2:00:00:00") == "Apple"

    def test_resuelve_mac_raspberry_pi(self):
        from core.vendor_resolver import VendorResolver
        assert VendorResolver.resolve("B8:27:EB:00:00:00") == "Raspberry Pi"

    def test_detecta_mac_aleatorizada(self):
        from core.vendor_resolver import VendorResolver
        # El bit U/L del primer octeto en 0x02 = MAC local/aleatoria
        assert VendorResolver.resolve(
            "02:00:00:00:00:00") == "MAC aleatorizada"

    def test_resultado_queda_en_cache(self):
        from core.vendor_resolver import VendorResolver
        VendorResolver.resolve("8C:64:A2:00:00:00")
        assert "8C:64:A2:00:00:00" in VendorResolver._cache

    def test_mac_vacia_devuelve_desconocido(self):
        from core.vendor_resolver import VendorResolver
        assert VendorResolver.resolve("") == "Desconocido"

    def test_validar_mac_formato_correcto(self):
        from core.vendor_resolver import VendorResolver
        assert VendorResolver.is_valid_mac("AA:BB:CC:DD:EE:FF") is True

    def test_validar_mac_formato_incorrecto(self):
        from core.vendor_resolver import VendorResolver
        assert VendorResolver.is_valid_mac("no-es-una-mac") is False

    def test_api_remota_falla_graciosamente(self):

        from core.vendor_resolver import VendorResolver
        with patch("requests.get", side_effect=Exception("timeout")):
            resultado = VendorResolver.resolve("F0:00:00:00:00:00")
        assert resultado == "Desconocido"
