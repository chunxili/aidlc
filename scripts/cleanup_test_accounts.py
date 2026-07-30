"""清理验收脚本留下的临时账号（D-CR002-1）。

为什么需要这个工具：`scripts/` 下的验收脚本为保证可重复运行，账号名都带随机后缀
（`operator_82215d20`、`pending_ddd6dd09`、`idem_5c2ea445`）。它们跑完就成了库里的垃圾，
而且会带着「待审OPERATOR」这类占位姓名出现在管理员的审核队列里，让成品看起来像半成品。

判定依据是**账号名形态**而非创建时间：形如 `<前缀>_<8位十六进制>` 的账号只可能由脚本生成，
真人注册不会产出这种名字。种子账号（admin001/op001/verifier001/user001）与真人注册的账号
都不匹配该形态，因此不会被误删。

外键处理：账号可能已产生活动、券、风控事件。直接删 users 会被外键拒绝，
所以按引用顺序先删从表。**不做级联删除**：级联会让一次误操作删掉真实业务数据且无从察觉。

用法：
    python scripts/cleanup_test_accounts.py            # 只报告，不删
    python scripts/cleanup_test_accounts.py --apply    # 实际删除
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src" / "backend"))

from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal  # noqa: E402

# 形如 <任意前缀>_<8 位十六进制>。POSIX 正则，PostgreSQL 的 ~ 运算符。
#
# 前缀部分必须允许下划线：脚本里有 `v_ok_8f2804ef`、`v_rej_1a2b3c4d` 这类多段前缀，
# 早先写成 `[a-z0-9]*` 时它们全部漏网，导致 9 个「通过核销员」长期留在核销人员名册里。
TEST_ACCOUNT_PATTERN = r"^[a-z][a-z0-9_]*_[0-9a-f]{8}$"

# 从表 → 指向 users 的列。按此顺序清理，最后才删 users。
DEPENDENTS: list[tuple[str, tuple[str, ...]]] = [
    ("user_coupons", ("user_id", "used_by")),
    ("risk_events", ("user_id", "handled_by")),
    ("ai_invocations", ("user_id",)),
    ("campaigns", ("created_by",)),
    ("users", ("reviewed_by",)),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="清理验收脚本留下的临时账号")
    parser.add_argument("--apply", action="store_true", help="实际执行删除，缺省仅报告")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        targets = db.execute(
            text(
                "SELECT id, username, display_name, role, status FROM users"
                " WHERE username ~ :pat ORDER BY role, username"
            ),
            {"pat": TEST_ACCOUNT_PATTERN},
        ).all()

        if not targets:
            print("未发现测试残留账号，库是干净的。")
            return 0

        print(f"匹配到 {len(targets)} 个测试残留账号：")
        for row in targets:
            print(f"  {row.username:<22} {row.role:<9} {row.status:<8} {row.display_name}")

        ids = [row.id for row in targets]

        # 报告受牵连的业务数据，让人在删之前看清代价
        print("\n关联业务数据：")
        for table, columns in DEPENDENTS:
            if table == "users":
                continue
            cond = " OR ".join(f"{c} = ANY(:ids)" for c in columns)
            n = db.execute(text(f"SELECT count(*) FROM {table} WHERE {cond}"), {"ids": ids}).scalar_one()
            print(f"  {table:<16} {n} 行")

        if not args.apply:
            print("\n仅报告模式。确认无误后加 --apply 执行删除。")
            return 0

        # 置空可空的引用列，删除强引用的行
        db.execute(text("UPDATE users SET reviewed_by = NULL WHERE reviewed_by = ANY(:ids)"), {"ids": ids})
        db.execute(text("UPDATE risk_events SET handled_by = NULL WHERE handled_by = ANY(:ids)"), {"ids": ids})
        db.execute(text("UPDATE ai_invocations SET user_id = NULL WHERE user_id = ANY(:ids)"), {"ids": ids})
        db.execute(
            text(
                "DELETE FROM risk_events WHERE user_id = ANY(:ids)"
                " OR campaign_id IN (SELECT id FROM campaigns WHERE created_by = ANY(:ids))"
            ),
            {"ids": ids},
        )
        db.execute(
            text(
                "DELETE FROM user_coupons WHERE user_id = ANY(:ids) OR used_by = ANY(:ids)"
                " OR campaign_id IN (SELECT id FROM campaigns WHERE created_by = ANY(:ids))"
            ),
            {"ids": ids},
        )
        db.execute(text("DELETE FROM campaigns WHERE created_by = ANY(:ids)"), {"ids": ids})
        deleted = db.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": ids}).rowcount
        db.commit()

        remaining = db.execute(
            text("SELECT count(*) FROM users WHERE username ~ :pat"), {"pat": TEST_ACCOUNT_PATTERN}
        ).scalar_one()
        print(f"\n已删除 {deleted} 个账号，剩余匹配 {remaining} 个。")
        return 0 if remaining == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
