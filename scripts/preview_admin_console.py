"""把管理员后台三个页面的真实返回渲染成文本表格，用于不开浏览器时核对效果。

不改任何数据，纯 GET。
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"


def get(path: str, token: str):
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def login(username: str, password: str = "Coupon@2026") -> str:
    req = urllib.request.Request(
        BASE + "/api/auth/login",
        data=json.dumps({"username": username, "password": password}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))["access_token"]


def table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [
        max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows else len(str(h))
        for i, h in enumerate(headers)
    ]
    line = "  ".join(str(h).ljust(w) for h, w in zip(headers, widths))
    print("  " + line)
    print("  " + "  ".join("-" * w for w in widths))
    for r in rows:
        print("  " + "  ".join(str(c).ljust(w) for c, w in zip(r, widths)))


def main() -> int:
    token = login("admin001")

    print("\n============ 侧栏「权限审批与管理」 ============")

    print("\n【注册审核】待处理申请")
    pending = get("/api/admin/registrations", token)
    print(f"  角标数字：{len(pending)}")
    table(
        ["姓名", "账号", "申请角色", "申请门店", "手机号"],
        [
            [p["display_name"], p["username"], p["role"], p.get("store_name") or "—", p.get("phone") or "—"]
            for p in pending
        ],
    )

    print("\n【核销人员】名册（姓名列只显示姓名）")
    verifiers = get("/api/admin/verifiers", token)
    table(
        ["姓名", "手机号", "状态", "行政区", "门店", "累计核销"],
        [
            [v["display_name"], v.get("phone") or "—", v["status"], v["store_district"], v["store_name"], v["redeemed_count"]]
            for v in verifiers
        ],
    )

    busiest = max(verifiers, key=lambda v: v["redeemed_count"])
    if busiest["redeemed_count"] > 0:
        print(f"\n  ↳ 点击「{busiest['display_name']}」展开抽屉 · 核销记录")
        rec = get(f"/api/admin/verifiers/{busiest['id']}/redemptions", token)
        v = rec["verifier"]
        print(f"    人员信息：{v['display_name']} / {v['username']} / {v.get('phone') or '—'} / {v['store_district']} {v['store_name']}")
        print(f"    共 {rec['total']} 条")
        table(
            ["券码", "活动", "优惠", "订单金额", "优惠额", "实付", "核销时间", "门店"],
            [
                [
                    i["code"], i["campaign_name"], i["benefit_text"],
                    f"¥{i['order_amount']}" if i["order_amount"] else "—",
                    f"-¥{i['discount_amount']}" if i["discount_amount"] else "—",
                    f"¥{i['payable_amount']}" if i["payable_amount"] else "—",
                    i["used_at"][:19].replace("T", " "),
                    i.get("store_name") or "—",
                ]
                for i in rec["items"]
            ],
        )
    else:
        print("\n  ↳ 当前无人有核销记录，抽屉会显示「该核销人员暂无核销记录」")

    print("\n【运营人员】名册")
    operators = get("/api/admin/operators", token)
    table(
        ["姓名", "手机号", "状态", "发布活动", "投放总量", "已领取", "已核销", "核销率"],
        [
            [
                o["display_name"], o.get("phone") or "—", o["status"],
                o["campaign_count"], o["total_stock"], o["claimed_count"], o["used_count"],
                f"{o['redeem_rate'] * 100:.1f}%" if o["redeem_rate"] is not None else "—",
            ]
            for o in operators
        ],
    )

    top = max(operators, key=lambda o: o["campaign_count"])
    if top["campaign_count"] > 0:
        print(f"\n  ↳ 点击「{top['display_name']}」展开抽屉 · 发布的券")
        drill = get(f"/api/admin/operators/{top['id']}/campaigns?page_size=10", token)
        print(f"    共 {drill['total']} 个活动")
        table(
            ["活动", "券型", "优惠", "投放", "已领取", "已核销", "剩余", "状态"],
            [
                [
                    c["name"], c["coupon_type"], c["benefit_text"],
                    c["total_stock"], c["claimed_count"], c["used_count"], c["remaining_stock"], c["status"],
                ]
                for c in drill["items"]
            ],
        )
    else:
        print("\n  ↳ 当前无人发布过活动，抽屉会显示「该运营人员尚未发布活动」")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
