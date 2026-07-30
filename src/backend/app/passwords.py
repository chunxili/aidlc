"""口令杂凑（ADR-011、NFR-012）。

用 hashlib.scrypt（Python 标准库）+ 每用户 16 字节随机盐。

选它而不是 bcrypt / argon2 的理由：**不引入新依赖**。scrypt 是内存硬化 KDF，
抗 GPU 暴破，安全性足够；后两者需要额外的 C 扩展包，在不可控的部署机上
多一个安装失败点。

明确禁止：明文存储、无盐杂凑、快速杂凑（MD5 / SHA1 / 裸 SHA256）。
这些不是"简化"，是缺陷。

杂凑串格式：scrypt$n$r$p$salt_hex$hash_hex
参数内嵌于串中，因此日后上调参数时旧口令仍可校验。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

# scrypt 参数。n 越大越抗暴破，同时越耗内存与时间。
# n=2^14 在本机实测约 60~80ms，对登录接口是可接受的成本。
_N = 1 << 14
_R = 8
_P = 1
_DKLEN = 32
_SALT_BYTES = 16

MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN
    )
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    """校验口令。

    用 hmac.compare_digest 做常量时间比较，避免通过响应时间旁路推断杂凑。
    stored 为空（历史遗留的无口令账号）时一律拒绝，不给"空密码可登录"的缺口。
    """
    if not stored:
        return False
    try:
        scheme, n_s, r_s, p_s, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n_s),
            r=int(r_s),
            p=int(p_s),
            dklen=len(hash_hex) // 2,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), hash_hex)
