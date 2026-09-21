import sys

from fastapi import HTTPException

SERVICE = "ScholarMate"
ACCOUNT = "deepseek-api-key"


def vault():
    # Explicit native backends: never fall back to a plaintext keyring.
    if sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring

        return WinVaultKeyring()
    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring

        return Keyring()
    raise HTTPException(503, "当前版本仅支持 Windows 或 macOS 系统凭据管理器。")


def get_key():
    try:
        return vault().get_password(SERVICE, ACCOUNT)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "无法访问系统凭据管理器，请检查系统解锁状态。") from None


def save_key(key):
    try:
        vault().set_password(SERVICE, ACCOUNT, key)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "API Key 保存失败，请检查系统凭据管理器。") from None

