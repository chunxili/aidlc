"""券码生成（FR-014、ADR-010、NFR-006）。

设计要点：核销**仅凭券码、不校验归属**（因核销由核销人员执行）。因此券码可预测
等价于任意人可枚举并批量核销他人券 —— 这是安全约束，不是编码偏好。

字符集为 Crockford Base32，剔除易混淆的 0/O 与 1/I/L：核销人员需人工读写券码。
10 位 × log2(32) = 50 位熵，枚举不可行。UUID4 被否是因为 36 字符人念不出、输不对。
"""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import code_generation_failed
from ..models import UserCoupon

# Crockford Base32 去掉 0 O 1 I L，余 27 个字符
ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 10
MAX_ATTEMPTS = 5


def generate_code() -> str:
    """用密码学安全随机源生成一个券码，不含任何可推导信息。"""
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def generate_unique_code(db: Session) -> str:
    """生成库内唯一的券码。

    冲突重试至多 MAX_ATTEMPTS 次，耗尽则整笔领取失败。
    **不得静默降级为可预测码** —— 那会把安全约束换成可用性，方向是错的。
    唯一索引仍是最终防线，此处的预查只是减少事务回滚。
    """
    for _ in range(MAX_ATTEMPTS):
        code = generate_code()
        exists = db.execute(
            select(UserCoupon.id).where(UserCoupon.code == code).limit(1)
        ).scalar_one_or_none()
        if exists is None:
            return code
    raise code_generation_failed()
