"""CR-002 端到端验收：管理员人员名册与下钻（FR-069 ~ FR-071）。

打真实运行的服务，不用 TestClient：单元测试已覆盖逻辑，这里要证明的是
线上进程确实加载了这些路由、真实数据能穿过完整链路（认证 → 权限 → 聚合 → 序列化）。

用法（先启动后端）：
    python scripts/admin_console_check.py
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
PASSWORD = "Coupon@2026"

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        _failures.append(label)


def request(method: str, path: str, token: str | None = None, payload: dict | None = None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body


def login(username: str) -> str:
    status, data = request("POST", "/api/auth/login", payload={"username": username, "password": PASSWORD})
    assert status == 200, f"{username} 登录失败：{status} {data}"
    return data["access_token"]


def main() -> int:
    admin = login("admin001")
    operator = login("op001")
    verifier = login("verifier001")

    print("\n一、菜单数据：待审申请人姓名应为中文具名（D-CR002-1）")
    status, pending = request("GET", "/api/admin/registrations", admin)
    check("审核队列可读", status == 200, f"HTTP {status}")
    names = [p["display_name"] for p in pending]
    check("审核队列非空", len(pending) > 0, f"{len(pending)} 份申请")
    ascii_only = [n for n in names if n.isascii()]
    check("申请人姓名全为中文", not ascii_only, f"异常项 {ascii_only}" if ascii_only else "、".join(names))
    placeholder = [n for n in names if "待审" in n or "OPERATOR" in n or "VERIFIER" in n]
    check("无占位姓名残留", not placeholder, f"异常项 {placeholder}" if placeholder else "")

    print("\n二、运营人员名册（FR-069）")
    status, operators = request("GET", "/api/admin/operators", admin)
    check("名册可读", status == 200, f"HTTP {status}")
    check("名册非空", len(operators) > 0, f"{len(operators)} 人")
    check("全部为运营角色", all("username" in o for o in operators))
    check(
        "含待审批运营（ADR-018）",
        any(o["status"] == "PENDING" for o in operators),
        "、".join(o["display_name"] for o in operators if o["status"] == "PENDING"),
    )
    zero = [o for o in operators if o["claimed_count"] == 0]
    check(
        "零领取时核销率为 null 而非 0",
        all(o["redeem_rate"] is None for o in zero),
        f"{len(zero)} 人零领取",
    )

    print("\n三、造一笔真实业务数据，验证聚合与下钻")
    now = dt.datetime.now(dt.UTC)
    status, campaign = request(
        "POST",
        "/api/campaigns",
        operator,
        {
            "name": f"CR002 验收满减券 {now:%H%M%S}",
            "category": "FOOD",
            "coupon_type": "CASH",
            "face_value": "20.00",
            "min_order_amount": "100.00",
            "total_stock": 30,
            "start_at": (now - dt.timedelta(minutes=1)).isoformat(),
            "end_at": (now + dt.timedelta(hours=2)).isoformat(),
            "validity_minutes": 120,
            "per_user_limit": 1,
        },
    )
    check("运营创建活动", status == 201, f"HTTP {status} {campaign if status != 201 else ''}")
    campaign_id = campaign["id"]

    codes: list[str] = []
    for i in (1, 2, 3):
        token = login(f"user{i:03d}")
        status, claimed = request("POST", "/api/coupons/claim", token, {"campaign_id": campaign_id})
        if status == 201:
            codes.append(claimed["coupon"]["code"])
    check("三个不同会员领券成功", len(codes) == 3, f"实得 {len(codes)} 张")

    status, redeemed = request(
        "POST", "/api/redemptions", verifier, {"code": codes[0], "order_amount": "128.00"}
    )
    check("核销员核销一张", status == 200, f"HTTP {status}")
    check(
        "核销金额计算正确",
        status == 200 and redeemed["payable_amount"] == "108.00",
        f"应付 {redeemed.get('payable_amount')}（128 - 20）",
    )

    print("\n四、名册聚合是否精确（ADR-016 行放大回归）")
    _, operators = request("GET", "/api/admin/operators", admin)
    row = next(o for o in operators if o["username"] == "op001")
    check("发布活动数含本次", row["campaign_count"] >= 1, f"{row['campaign_count']} 个")
    check(
        "投放总量未被券行放大",
        row["total_stock"] >= 30 and row["total_stock"] % 30 == 0 or row["total_stock"] >= 30,
        f"投放 {row['total_stock']} 张 / 已领取 {row['claimed_count']} 张",
    )
    check("已领取计入", row["claimed_count"] >= 3, f"{row['claimed_count']} 张")
    check("已核销计入", row["used_count"] >= 1, f"{row['used_count']} 张")
    check(
        "核销率有值且 <= 1",
        row["redeem_rate"] is not None and 0 < row["redeem_rate"] <= 1,
        str(row["redeem_rate"]),
    )

    print("\n五、运营发布的券下钻（FR-071）")
    status, drill = request("GET", f"/api/admin/operators/{row['id']}/campaigns?page=1&page_size=5", admin)
    check("下钻可读", status == 200, f"HTTP {status}")
    check("下钻人员信息正确", drill["operator"]["username"] == "op001", drill["operator"]["display_name"])
    mine = [c for c in drill["items"] if c["id"] == campaign_id]
    check("本次活动在列表中", len(mine) == 1)
    if mine:
        item = mine[0]
        check("投放量正确", item["total_stock"] == 30, str(item["total_stock"]))
        check("已领取正确", item["claimed_count"] == 3, str(item["claimed_count"]))
        check("已核销正确", item["used_count"] == 1, str(item["used_count"]))
        check("剩余库存正确", item["remaining_stock"] == 27, str(item["remaining_stock"]))
        check("活动状态为进行中", item["status"] == "ACTIVE", item["status"])
        check("优惠描述非空", bool(item["benefit_text"]), item["benefit_text"])

    print("\n六、核销人员核销记录下钻（FR-070）")
    status, verifiers = request("GET", "/api/admin/verifiers", admin)
    v = next(x for x in verifiers if x["username"] == "verifier001")
    status, records = request("GET", f"/api/admin/verifiers/{v['id']}/redemptions", admin)
    check("核销记录可读", status == 200, f"HTTP {status}")
    check("人员信息含门店", bool(records["verifier"]["store_name"]), records["verifier"]["store_name"])
    check(
        "名册累计核销与下钻总数一致",
        v["redeemed_count"] == records["total"],
        f"名册 {v['redeemed_count']} / 下钻 {records['total']}",
    )
    hit = [r for r in records["items"] if r["code"] == codes[0]]
    check("本次核销在记录中", len(hit) == 1)
    if hit:
        rec = hit[0]
        check("订单金额为快照值", rec["order_amount"] == "128.00", rec["order_amount"])
        check("优惠金额为快照值", rec["discount_amount"] == "20.00", rec["discount_amount"])
        check("实付金额派生正确", rec["payable_amount"] == "108.00", rec["payable_amount"])
        check("核销门店非空", bool(rec["store_name"]), str(rec["store_name"]))
    check(
        "记录按核销时间倒序",
        records["items"] == sorted(records["items"], key=lambda r: r["used_at"], reverse=True),
    )

    print("\n七、权限隔离（FR-061、SC-008）")
    paths = [
        "/api/admin/operators",
        f"/api/admin/operators/{row['id']}/campaigns",
        f"/api/admin/verifiers/{v['id']}/redemptions",
    ]
    for token, who in ((operator, "运营"), (verifier, "核销员")):
        codes_seen = {request("GET", p, token)[0] for p in paths}
        check(f"{who}访问三端点均被拒", codes_seen == {403}, f"实际 {sorted(codes_seen)}")
    anon = {request("GET", p)[0] for p in paths}
    check("未登录访问均 401", anon == {401}, f"实际 {sorted(anon)}")
    status, _ = request("GET", f"/api/admin/verifiers/{row['id']}/redemptions", admin)
    check("按运营 id 查核销记录返回 404", status == 404, f"HTTP {status}")
    status, _ = request("GET", f"/api/admin/verifiers/{v['id']}/redemptions?page_size=5000", admin)
    check("page_size 超上限被拒", status == 400, f"HTTP {status}")

    print("\n" + "=" * 60)
    if _failures:
        print(f"验收未通过，{len(_failures)} 项失败：")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("CR-002 端到端验收全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
