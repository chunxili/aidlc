# API 设计 — 优惠券发放与核销中心

前缀 `/api`。认证：`Authorization: Bearer <JWT>`。角色枚举：`OPERATOR` / `USER` / `VERIFIER` / `ADMIN`。
时间字段一律 ISO 8601 带时区（UTC，NFR-005）。金额为字符串形式的十进制数，避免浮点误差。

## 一、通用错误响应

```json
{ "code": "OUT_OF_STOCK", "message": "库存不足" }
```

| HTTP | code | 触发条件 |
|---|---|---|
| 400 | `VALIDATION_ERROR` | 入参非法，附 `details` 字段级说明 |
| 401 | `UNAUTHENTICATED` | 缺失/过期/签名无效的 JWT，不区分原因 |
| 403 | `FORBIDDEN` | 角色越权。响应体**不含**目标资源任何字段（SC-008） |
| 403 | `RISK_BLOCKED` | 风控硬阈值拦截（FR-050） |
| 403 | `RISK_MANUAL_REVIEW` | 风控判定需人工审核（FR-050） |
| 404 | `CAMPAIGN_NOT_FOUND` / `COUPON_NOT_FOUND` | |
| 409 | `OUT_OF_STOCK` | 库存不足 |
| 409 | `PER_USER_LIMIT_REACHED` | 已达领取上限（`per_user_limit=1` 时即"已领取"场景） |
| 409 | `CAMPAIGN_NOT_ACTIVE` | 活动未开始或已结束 |
| 409 | `COUPON_ALREADY_USED` | 已核销 |
| 409 | `COUPON_EXPIRED` | 券已过期 |
| 409 | `STOCK_CANNOT_DECREASE` | 试图调低库存 |
| 409 | `FIELD_IMMUTABLE` | 修改不可变字段 |
| 500 | `INTERNAL_ERROR` | 不含堆栈与凭证 |

**AI 故障不产生错误码**：一律降级并以响应体内 `degraded` 标识（FR-041、FR-051）。

分页统一 `?page=1&page_size=20`，响应 `{ "items": [...], "total": N, "page": 1, "page_size": 20 }`。

## 二、认证

### POST /api/auth/login — 全部角色

请求 `{ "username": "user_a" }`。Mock 认证，不校验密码（FR-060）。

响应 200：
```json
{ "access_token": "<jwt>", "token_type": "bearer",
  "user": { "id": 3, "username": "user_a", "display_name": "用户A", "role": "USER" } }
```

错误：401 `UNAUTHENTICATED`（用户不存在）。

### GET /api/auth/me — 全部角色

返回当前 token 对应用户。用于前端刷新后恢复登录态。

## 三、活动管理

### POST /api/campaigns — `OPERATOR`

```json
{ "name": "周末餐饮券", "category": "FOOD", "face_value": "20.00",
  "total_stock": 100, "start_at": "2026-07-30T00:00:00Z", "end_at": "2026-08-06T00:00:00Z",
  "validity_minutes": 1440, "per_user_limit": 1 }
```

规则：`total_stock>=1`、`face_value>0`、`end_at>start_at`、`validity_minutes>=1`、`per_user_limit>=1`（缺省 1）。**不预生成任何券记录**（ADR-001）。

响应 201：活动完整字段 + `claimed_count: 0` + `remaining_stock` + 派生 `status`。
错误：400、403。

### PATCH /api/campaigns/{id} — `OPERATOR`

可改 `name`、`category`、`end_at`、`per_user_limit`、`total_stock`（**仅调高**）。
不可改 `face_value`、`validity_minutes`、已开始活动的 `start_at`。

`validity_minutes` 不可改的原因：已领出券的 `expires_at` 已落库（ADR-003），改它会使同一活动内的券遵循两套规则。

错误：409 `STOCK_CANNOT_DECREASE`、409 `FIELD_IMMUTABLE`、404、403。

### GET /api/campaigns — `OPERATOR` / `ADMIN`

分页返回全部活动，含 `claimed_count`、`remaining_stock`、派生 `status`（`PENDING` / `ACTIVE` / `ENDED`，由 `start_at`/`end_at` 与 `now()` 计算，不落库，ADR-002）。
查询参数：`status`、`category`。

### GET /api/campaigns/available — `USER`

返回**当前可领**的活动：`ACTIVE` 且 `claimed_count < total_stock` 且该用户已领数 `< per_user_limit`。
不下发统计与风控字段（最小权限）。附 `my_claimed_count`，供前端展示剩余可领次数。

### GET /api/campaigns/{id} — `OPERATOR` / `ADMIN`

单个活动详情 + FR-030 指标。

## 四、领券

### POST /api/coupons/claim — `USER`

```json
{ "campaign_id": 12 }
```

执行顺序（system-architecture.md 第三节时序图）：风控前置（事务外）→ 条件 UPDATE 扣库存 → 计算 seq 与限领校验 → 生成券码 → 计算 `expires_at` → INSERT。

响应 201：
```json
{ "coupon": { "id": 88, "code": "7K4MPQ2XZ9", "campaign_id": 12, "campaign_name": "周末餐饮券",
              "face_value": "20.00", "status": "UNUSED", "seq": 1,
              "claimed_at": "2026-07-30T02:00:00Z", "expires_at": "2026-07-30T02:01:00Z" },
  "risk": { "score": 12, "decision": "PASS", "decided_by": "RULE", "degraded": false } }
```

错误：409 `OUT_OF_STOCK`、409 `PER_USER_LIMIT_REACHED`、409 `CAMPAIGN_NOT_ACTIVE`、403 `RISK_BLOCKED`、403 `RISK_MANUAL_REVIEW`、404、403 越权。

**幂等性说明**：领券**不是**幂等操作（`per_user_limit>1` 时重复调用应各得一张券）。防重复由 `per_user_limit` + `UNIQUE(campaign_id,user_id,seq)` 承担，不引入幂等键。

**关键约束**：本接口调用链中不得出现 Bedrock 调用，除非风控落入灰区（FR-010 AC-5）。

### GET /api/coupons/my — `USER`

分页返回本人券。过滤条件强制取自 token 的 `sub`，**忽略客户端传入的任何 user_id**（FR-011）。
每项含派生 `display_status`：`USED` → `已核销`；`UNUSED` 且未到期 → `可用`；`UNUSED` 且已到期 → `已过期`（ADR-002）。
查询参数：`display_status`。

## 五、核销

### GET /api/redemptions/{code} — `VERIFIER`

核销前查验，**纯读，不改变任何状态**（FR-021）。

响应 200：
```json
{ "code": "7K4MPQ2XZ9", "campaign_name": "周末餐饮券", "face_value": "20.00",
  "display_status": "可用", "owner": "u***_a", "redeemable": true, "reason": null }
```

`owner` 脱敏。`redeemable=false` 时 `reason` 与 POST 的判定口径**完全一致**（FR-021 AC-2）。
错误：404 `COUPON_NOT_FOUND`、403。

### POST /api/redemptions — `VERIFIER`

```json
{ "code": "7K4MPQ2XZ9" }
```

单条条件 UPDATE。`rowcount=0` 时回查并按 **status 优先、时间其次**判定（ADR-004）。

响应 200：
```json
{ "code": "7K4MPQ2XZ9", "face_value": "20.00",
  "used_at": "2026-07-30T02:00:30Z", "used_by": "verifier001" }
```

错误：
- 409 `COUPON_ALREADY_USED` —— **重复核销返回此项，且第 2、3、4 次响应体完全一致**（NFR-002、SC-004）
- 409 `COUPON_EXPIRED`
- 404 `COUPON_NOT_FOUND`
- 403 越权

**终态优先**：已核销的券在过期后再核销，返回 `COUPON_ALREADY_USED` 而非 `COUPON_EXPIRED`（ADR-004）。

## 六、AI 推荐

### GET /api/recommendations — `USER`

独立只读接口，**不在领券路径上**（ADR-005）。参数 `?limit=5`。

响应 200：
```json
{ "items": [ { "campaign_id": 12, "campaign_name": "周末餐饮券", "category": "FOOD",
               "face_value": "20.00", "remaining_stock": 87, "reason": "你最近核销过 2 张餐饮券…" } ],
  "degraded": false, "degrade_reason": null, "cold_start": false }
```

约束：
- 候选集为确定性 SQL 召回，AI 只重排并生成理由；返回的 `campaign_id` **逐个校验在候选白名单内，不在的丢弃**（ADR-009）
- 已过期、已售罄、该用户已领满的活动永不出现
- 冷启动（零历史）时 `cold_start=true`，按热度排序并使用新人话术
- **列表非空是硬保证**：AI 不可用时降级为热度排序 + 模板理由，`degraded=true`（FR-041）
- 候选集本身为空（确无可领活动）时返回空数组，属合法状态，不是错误

## 七、风控与风险标记

### GET /api/risk/events — `OPERATOR`

分页返回风险标记，参数 `status`（`PENDING`/`RELEASED`/`KEPT`）、`user_id`。

每项含：`user`、`window_request_count`、`risk_score`、`decision`、`decided_by`、`degraded`、`created_at`、以及 **`ai_reason`**（经 `ai_invocation_id` 关联取出的判定理由）。

`ai_reason` 是必需字段而非附加信息：运营若看不到判定理由，无从审核标记（FR-052 AC-2）。规则层直接拦截时该字段为规则说明文本（如"10 秒内 50 次请求，超过硬阈值 10"）。

### POST /api/risk/events/{id}/handle — `OPERATOR`

```json
{ "action": "RELEASE" }
```

`RELEASE` → 标记置 `RELEASED` 并清除 `users.risk_blocked`，用户可自行重领；`KEEP` → 置 `KEPT`，限制保留。

**幂等**：重复处理同一标记返回当前状态，不报错（FR-052）。
错误：404、403。

**不存在"批准发券"接口**：审核对象是风险标记，不是待批领取；系统不代为补发，用户走正常领取路径（ADR-007）。

## 八、统计

### GET /api/stats/campaigns/{id} — `ADMIN` / `OPERATOR`

```json
{ "campaign_id": 12, "total_stock": 100, "claimed_count": 13, "remaining_stock": 87,
  "used_count": 5, "active_count": 6, "expired_count": 2,
  "claim_rate": 0.13, "redeem_rate": 0.3846,
  "claim_rate_basis": "分母为库存总量（系统无曝光埋点）",
  "redeem_rate_basis": "分母为已领取数" }
```

两个 `*_basis` 字段是设计的一部分，用于前端直接展示口径说明（FR-030 AC-4）。`claimed_count = 0` 时 `redeem_rate` 为 `null`，前端显示「—」。

### GET /api/stats/overview — `ADMIN`

全局汇总 + **异常指标**（FR-031）：

```json
{ "campaign_count": 4, "total_stock": 400, "claimed_count": 51, "used_count": 20,
  "risk_blocked_24h": 40, "risk_pending_count": 1 }
```

`risk_blocked_24h` 在 SC-006 演示后应当场增加，是风控真实生效的最直观证据。

### GET /api/stats/integrity — `ADMIN`

对账自检端点，返回 INV-1 / INV-2 的校验结果：

```json
{ "inv1_stock_overflow_count": 0, "inv2_mismatch_campaign_ids": [], "ok": true }
```

设置该端点的目的：让"库存守恒"与"券的完全划分"可在演示时一键展示，而非只存在于文档里（NFR-009）。

## 九、运维

### GET /api/health — 公开

```json
{ "status": "ok", "database": "ok", "ai_configured": false }
```

`ai_configured=false` 表示未注入 Bedrock 凭证，AI 功能处于降级模式。**该状态不影响 `status: ok`**（FR-071 AC-2）。

## 十、路由与角色映射（FR-061 强制表）

| 方法与路径 | 允许角色 |
|---|---|
| POST /api/auth/login、GET /api/health | 公开 |
| GET /api/auth/me | 全部已认证 |
| POST /api/campaigns、PATCH /api/campaigns/{id} | OPERATOR |
| GET /api/campaigns、GET /api/campaigns/{id} | OPERATOR, ADMIN |
| GET /api/campaigns/available | USER |
| POST /api/coupons/claim、GET /api/coupons/my | USER |
| GET /api/recommendations | USER |
| GET /api/redemptions/{code}、POST /api/redemptions | VERIFIER |
| GET /api/risk/events、POST /api/risk/events/{id}/handle | OPERATOR |
| GET /api/stats/campaigns/{id} | ADMIN, OPERATOR |
| GET /api/stats/overview、GET /api/stats/integrity | ADMIN |

此表是 SC-008 权限验收的直接依据，实现时应由单一装饰器/依赖强制，不得散落在处理函数内部。

## 十一、无 Webhook

本项目无外部回调与消息通知（MVP 范围外），故不设计 Webhook 及其签名校验。

---

## 十二、CR-001 新增端点：注册、门店与审核

### POST /api/auth/register — 公开

请求：`{ username, password, display_name, role, phone?, store_id? }`

`role ∈ {USER, VERIFIER, OPERATOR}`。`ADMIN` 不可自助注册（自举问题，由 seed 解决）。
`VERIFIER` 必填 `store_id`；其余角色不得携带 `store_id`。

响应 `201`：`{ user: User, needs_approval: bool }`。`USER` 即时 `ACTIVE`（`needs_approval=false`），
`VERIFIER`/`OPERATOR` 为 `PENDING`（`needs_approval=true`）。

错误：`400 VALIDATION_ERROR`（账号少于 4 字符、口令少于 8 字符、姓名为空、门店缺失或不存在）、
`409 USERNAME_TAKEN`（该账号已被使用；若原账号为 `REJECTED` 则允许覆盖重投，返回 201）。

### GET /api/stores — 公开

响应：`[{ id, code, name, district, address }]`。注册页需在登录前展示门店，故公开。

### GET /api/stores/districts — 公开

响应：`["越秀区", "天河区", ...]`。供注册页与名册的行政区级联筛选。

### GET /api/admin/registrations — `ADMIN`

响应：`[{ id, username, display_name, role, phone, store_id, store_name, store_district, created_at }]`，
仅 `status = PENDING`，按提交时间升序。

### POST /api/admin/registrations/{user_id}/review — `ADMIN`

请求：`{ approve: bool, reason?: string }`。响应同上单条。

幂等：目标已非 `PENDING` 时不再变更，直接返回当前状态。驳回未给原因时落默认文案，
保证 `reject_reason` 在 `REJECTED` 状态下永不为空 —— 否则申请人看到的是无解释的拒绝。

错误：`404 USER_NOT_FOUND`。

### GET /api/admin/verifiers — `ADMIN`

查询参数：`district?`、`store_id?`。

响应：`[{ id, username, display_name, phone, status, store_id, store_code, store_name,
store_district, redeemed_count, created_at }]`。`redeemed_count` 为实时聚合（ADR-008、ADR-016）。

---

## 十三、CR-002 新增端点：运营名册与下钻

三个端点均为**只读**，均归 `ADMIN`。本期管理员对人员的唯一写操作仍是审批（ADR-018）。

### GET /api/admin/operators — `ADMIN`

全部运营人员名册，含投放业绩。

响应：

```json
[
  {
    "id": 12,
    "username": "op001",
    "display_name": "李彦",
    "phone": "13800000002",
    "status": "ACTIVE",
    "campaign_count": 3,
    "total_stock": 1300,
    "claimed_count": 412,
    "used_count": 87,
    "redeem_rate": 0.2112,
    "created_at": "2026-07-29T02:00:00Z"
  }
]
```

`redeem_rate = used_count / claimed_count`，`claimed_count` 为 0 时返回 `null` 而非 0 ——
「无人领取」与「领了没人用」是两回事，用 0 表示前者会误导运营复盘。分母口径与
`GET /api/stats/campaigns/{id}` 的 `redeem_rate_basis` 保持一致。

含 `PENDING` 与 `REJECTED` 账号：名册需要能看到「这个人还没审批」（ADR-018）。

### GET /api/admin/verifiers/{user_id}/redemptions — `ADMIN`

某核销员的核销记录，按核销时间倒序。

查询参数：`page`（默认 1）、`page_size`（默认 20，上限 100）。

响应：

```json
{
  "verifier": { "id": 5, "display_name": "王磊", "username": "verifier001",
                "phone": "13800000003", "store_name": "天河城店", "store_district": "天河区" },
  "items": [
    {
      "id": 9001,
      "code": "3H7K2M9QRT",
      "campaign_name": "周末餐饮满减",
      "coupon_type": "CASH",
      "benefit_text": "满 100 减 20",
      "order_amount": "128.00",
      "discount_amount": "20.00",
      "payable_amount": "108.00",
      "used_at": "2026-07-29T11:20:31Z",
      "store_name": "天河城店"
    }
  ],
  "total": 37,
  "page": 1,
  "page_size": 20
}
```

金额取核销时落库的快照，不用活动现值重算（ADR-017）。`payable_amount` 由
`order_amount - discount_amount` 派生，不落库。

错误：`404 USER_NOT_FOUND`（不存在或不是核销员）。

### GET /api/admin/operators/{user_id}/campaigns — `ADMIN`

某运营发布的活动列表，按创建时间倒序。界面文案称「发布的券」，数据粒度是**活动**（Q-023）。

查询参数：`page`、`page_size`（同上）。

响应：

```json
{
  "operator": { "id": 12, "display_name": "李彦", "username": "op001",
                "phone": "13800000002", "status": "ACTIVE" },
  "items": [
    {
      "id": 3,
      "name": "周末餐饮满减",
      "category": "FOOD",
      "coupon_type": "CASH",
      "benefit_text": "满 100 减 20",
      "total_stock": 500,
      "claimed_count": 412,
      "used_count": 87,
      "remaining_stock": 88,
      "status": "ACTIVE",
      "start_at": "2026-07-29T00:00:00Z",
      "end_at": "2026-07-31T00:00:00Z"
    }
  ],
  "total": 3,
  "page": 1,
  "page_size": 20
}
```

`status` 与 `remaining_stock` 均为派生值，口径与 `GET /api/campaigns` 完全一致（ADR-002）。

错误：`404 USER_NOT_FOUND`（不存在或不是运营）。

### 路由与角色映射增补（FR-061）

| 端点 | 角色 |
|---|---|
| `POST /api/auth/register` | 公开 |
| `GET /api/stores`、`GET /api/stores/districts` | 公开 |
| `GET /api/admin/registrations` | `ADMIN` |
| `POST /api/admin/registrations/{id}/review` | `ADMIN` |
| `GET /api/admin/verifiers` | `ADMIN` |
| `GET /api/admin/verifiers/{id}/redemptions` | `ADMIN` |
| `GET /api/admin/operators` | `ADMIN` |
| `GET /api/admin/operators/{id}/campaigns` | `ADMIN` |

---

# 十二、运营增强 v2 API 增量（CR-002）

> 保留现有端点兼容。新增响应字段均向后兼容；与旧风控裁决契约冲突时，以本节为准。

## 12.1 新增错误码

| HTTP | code | 含义 |
|---|---|---|
| 403 | `AUDIENCE_NOT_ELIGIBLE` | 用户未命中活动目标人群 |
| 409 | `CAMPAIGN_PAUSED` | 活动已暂停 |
| 409 | `CAMPAIGN_TERMINATED` | 活动已提前结束 |
| 409 | `OUTSIDE_CLAIM_WINDOW` | 不在每日领取时段 |
| 409 | `DAILY_LIMIT_REACHED` | 当日额度耗尽 |
| 409 | `INVALID_STATE_TRANSITION` | 非法活动状态转换 |
| 400 | `INVALID_POLICY` | 风控阈值/权重组合非法 |

## 12.2 活动创建与更新扩展

`POST /api/campaigns` 增加可选字段：

```json
{
  "daily_limit": 100,
  "claim_windows": [{"start":"10:00","end":"12:00"},{"start":"18:00","end":"20:00"}],
  "audience_segments": ["NEW","DORMANT"],
  "risk_policy": {"mode":"INHERIT"},
  "alert_overrides": null
}
```

缺省为 unlimited + 全天 + ALL + INHERIT。窗口重叠、ALL 与其他人群混选返回 400。

`PATCH /api/campaigns/{id}` 增加 `daily_limit`、`claim_windows`、`audience_segments`、`risk_policy`；优惠内容仍不可改。

新增动作：

- `POST /api/campaigns/{id}/pause` — OP，RUNNING→PAUSED。
- `POST /api/campaigns/{id}/resume` — OP，PAUSED→RUNNING；TERMINATED 不可恢复。
- `POST /api/campaigns/{id}/terminate` — OP，RUNNING/PAUSED→TERMINATED，需 `{ "confirm": true }`。
- `GET /api/campaigns/{id}/changes?page=&page_size=` — OP，配置变更日志。

活动响应增加 `manual_state`、`claimability`（可领与否及原因）、`daily_limit`、`today_claimed_count`、`claim_windows`、`audience_segments`、`risk_policy_summary`。

## 12.3 运营设置

- `GET /api/operator/settings` — OP。
- `PATCH /api/operator/settings/audiences` — OP，更新人群阈值并返回受影响运行中活动数。
- `PATCH /api/operator/settings/risk` — OP，更新全局默认策略；请求支持 LOW/MEDIUM/HIGH/CUSTOM。
- `PATCH /api/operator/settings/alerts` — OP，更新六类预设提醒的 enabled/threshold。
- `GET /api/operator/settings/changes?page=&page_size=` — OP。

PATCH 使用完整版本号 `expected_version` 做乐观并发控制；版本不匹配返回 409 `CONFIG_VERSION_CONFLICT`，避免两个运营页面互相覆盖。

## 12.4 风险事件与处置 v2

风险评估响应：

```json
{
  "score": 58,
  "decision": "MANUAL_REVIEW",
  "decided_by": "RULE",
  "policy": {"source":"CAMPAIGN_OVERRIDE","version":3,"level":"HIGH"},
  "factors": [
    {"code":"FREQUENCY","points":30,"evidence":{"window_count":6}},
    {"code":"NEW_ACCOUNT","points":15,"evidence":{"account_age_days":1}}
  ],
  "explanation":"…",
  "explanation_source":"AI"
}
```

`GET /api/risk/events` 新增筛选：`handling_status`、`campaign_id`、`decision`；只把 `handling_status=PENDING` 计入待办。

`POST /api/risk/events/{id}/handle` 请求改为：

```json
{ "action":"RELEASE" }
```

或：

```json
{ "action":"RESTRICT", "duration":"PT24H" }
```

允许 `PT1H`、`PT24H`、`P7D`、`PERMANENT`。限制只作用事件的 campaign；BLOCK/AUTO_BLOCKED 不可作为人工待办处理。重复同一处理返回当前状态。

## 12.5 运营驾驶舱

`GET /api/operator/dashboard` — OP。

查询：`range=today|7d|30d|custom`、`from`、`to`、`status`、`category`、重复 `campaign_id`（最多 3）。响应在单次数据库会话中使用统一 `as_of`：

```json
{
  "as_of":"2026-07-30T10:00:00Z",
  "timezone":"Asia/Shanghai",
  "summary":{
    "claims":120,"redemptions":51,"active_campaigns":4,
    "daily_quota_usage_rate":0.72,"pending_risks":3,"risk_block_rate":0.08
  },
  "series":[{"bucket":"2026-07-30T09:00:00+08:00","claims":20,"redemptions":8,"risk_requests":3,"remaining_quota":40}],
  "campaigns":[],
  "alerts":[]
}
```

`GET /api/operator/dashboard/campaigns/{id}` — OP，返回抽屉详情：业务指标、趋势、额度、风险构成、人群/策略摘要、提醒与最近变更。所有调控动作仍调用 campaign 动作/更新端点，不在统计端点产生写操作。

## 12.6 路由角色增量

| 方法与路径 | 允许角色 |
|---|---|
| POST `/api/campaigns/{id}/pause|resume|terminate` | OPERATOR |
| GET `/api/campaigns/{id}/changes` | OPERATOR |
| GET/PATCH `/api/operator/settings/**` | OPERATOR |
| GET `/api/operator/dashboard`、`/campaigns/{id}` | OPERATOR |

后端单一 `require_operator` 依赖强制。ADMIN 不自动继承运营写权限。
