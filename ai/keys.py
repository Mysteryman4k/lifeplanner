"""API keys, kept in Windows Credential Manager through `keyring`.

Never in the database, settings, backups or logs. The rest of the app only ever learns whether a key
is saved and its last 4 characters (so the student can tell which key it is).
Any program running as the same Windows user can read these entries; the terms and the Run notice say
so, and setup recommends a spending limit with the provider (stage 0.5 finding).
"""
import keyring

SERVICE = "EasyUniTrack AI"


def _backend():
    """Use the Windows vault directly on Windows, so packaged builds don't depend on entry-point
    discovery. Tests swap in an in-memory backend with keyring.set_keyring()."""
    import os
    if os.name == "nt" and type(keyring.get_keyring()).__name__ not in ("MemoryKeyring",):
        try:
            from keyring.backends.Windows import WinVaultKeyring
            if not isinstance(keyring.get_keyring(), WinVaultKeyring):
                keyring.set_keyring(WinVaultKeyring())
        except Exception:
            pass
    return keyring


def save(provider: str, key: str):
    _backend().set_password(SERVICE, provider, key)


def get(provider: str):
    try:
        return _backend().get_password(SERVICE, provider)
    except Exception:
        return None


def delete(provider: str):
    """Remove a saved key. A key that isn't there is fine; any other failure is raised, so the app
    never says a key was removed when it's still in Credential Manager."""
    from keyring.errors import PasswordDeleteError
    try:
        _backend().delete_password(SERVICE, provider)
    except PasswordDeleteError:
        pass


def hint(provider: str):
    """'…a1b2' for a saved key, or None."""
    key = get(provider)
    return f"…{key[-4:]}" if key and len(key) >= 8 else ("saved" if key else None)
