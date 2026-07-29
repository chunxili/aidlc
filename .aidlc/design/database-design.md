# 数据库设计 — 优惠券发放与核销中心

目标库：PostgreSQL 16（CON-004）。全部时间字段为 `timestamptz`，存 UTC，展示层转本地时区（NFR-005）。

## 一、实体关系

```mermaid
erDiagram
  users ||--o{ user_coupons : "领取"
  users ||--o{ risk_events : "触发"
  users ||--o{ user_coupons : "核销(used_by)"
  campaigns ||--o{ user_coupons : "发放"
  risk_events }o--|| ai_invocations : "判定依据"
```

五张表，无更多。刻意不建的表：券池表（ADR-001 计数器模型）、幂等键表（ADR-004 券码即幂等键）、统计汇总表（ADR-008 实时聚合）、作废记录表（无作废功能）。

## 二、表定义

### users（FR-060、FR-062）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | bigserial | PK | |
| username | varchar(64) | NOT NULL, UNIQUE | 登录标识 |
| display_name | varchar(64) | NOT NULL | |
| role | varchar(16) | NOT NULL, CHECK in (OPERATOR, USER, VERIFIER, ADMIN) | 角色由此单一来源决定 |
| risk_blocked | boolean | NOT NULL DEFAULT false | 存在未解除的风险标记时为 true（ADR-007） |
| created_at | timestamptz | NOT NULL DEFAULT now() | |

`role` 用 CHECK 约束而非外键表：四个角色是需求固定的枚举，不存在运营期新增角色的需求，独立角色表只会增加联表成本。

`risk_blocked` 是 `risk_events` 的派生便利字段，用于领券路径上的单次快速判断，避免每次领券都聚合 `risk_events`。它与 `risk_events` 的一致性由 `services/risk` 在同一事务内维护。

### campaigns（FR-001、FR-002、FR-003）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | bigserial | PK | |
| name | varchar(128) | NOT NULL | |
| category | varchar(32) | NOT NULL, CHECK in (FOOD, TRAVEL, SHOPPING, LIFE) | AI 生成推荐理由的语义来源（D-07） |
| face_value | numeric(10,2) | NOT NULL, CHECK > 0 | 面额。仅展示与推荐特征，不参与结算（CON-003） |
| total_stock | integer | NOT NULL, CHECK > 0 | |
| claimed_count | integer | NOT NULL DEFAULT 0, CHECK >= 0 | **单调递增，永不回退（INV-1）** |
| start_at | timestamptz | NOT NULL | |
| end_at | timestamptz | NOT NULL | |
| validity_minutes | integer | NOT NULL, CHECK >= 1 | 领取后有效时长，分钟（ADR-003） |
| per_user_limit | integer | NOT NULL DEFAULT 1, CHECK >= 1 | |
| created_by | bigint | FK users(id) | |
| created_at / updated_at | timestamptz | NOT NULL DEFAULT now() | |

表级约束：`CHECK (end_at > start_at)`、`CHECK (claimed_count <= total_stock)`。

第二条 CHECK 是 INV-1 的**数据库级兜底**：即使应用层写错，超发也会被数据库直接拒绝。这是把不变量从"约定"变成"强制"的关键一行。

**不存字段**：`status`（活动状态由 `start_at`/`end_at` 与 `now()` 派生，ADR-002）、`remaining_stock`（= `total_stock - claimed_count`，恒等式）。

索引：`(start_at, end_at)` 支持"进行中活动"查询；`(category)` 支持推荐召回。

### user_coupons（FR-010、FR-011、FR-014、FR-020）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | bigserial | PK | |
| campaign_id | bigint | NOT NULL, FK campaigns(id) | |
| user_id | bigint | NOT NULL, FK users(id) | 持有人 |
| seq | integer | NOT NULL, CHECK >= 1 | 该用户在本活动的第几张 |
| code | varchar(16) | NOT NULL, UNIQUE | 10 位 Crockford Base32（ADR-010） |
| status | varchar(8) | NOT NULL DEFAULT 'UNUSED', CHECK in (UNUSED, USED) | **仅两态（INV-3）** |
| claimed_at | timestamptz | NOT NULL DEFAULT now() | |
| expires_at | timestamptz | NOT NULL | `min(campaign.end_at, claimed_at + validity_minutes)`，落库（ADR-003） |
| used_at | timestamptz | NULL | 核销时间，审计 |
| used_by | bigint | NULL, FK users(id) | 核销人，审计（NFR-008） |

**关键约束 `UNIQUE (campaign_id, user_id, seq)`**：这一行索引就是"每用户限领数"的并发保障（ADR-001）。并发下两个请求算出同一个 `seq`，数据库拒绝其中一个，触发回滚，`claimed_count` 的 `+1` 随之撤销。

表级约束：`CHECK (status='USED' AND used_at IS NOT NULL AND used_by IS NOT NULL) OR (status='UNUSED' AND used_at IS NULL AND used_by IS NULL)` —— 使核销的三个字段无法出现不一致状态。

索引：
- `UNIQUE (code)`：核销的唯一入口是券码，此索引承载核销全部查询
- `(campaign_id, status)`：统计聚合（ADR-008）
- `(user_id, claimed_at DESC)`：我的券列表、推荐的用户历史特征
- `(user_id, claimed_at)`：风控窗口计数

**不存字段**：`is_expired`（惰性判断，ADR-002）。

### risk_events（FR-050、FR-052）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | bigserial | PK | |
| user_id | bigint | NOT NULL, FK users(id) | |
| campaign_id | bigint | NULL, FK campaigns(id) | 触发时的目标活动 |
| window_request_count | integer | NOT NULL | 窗口内请求数，判定依据 |
| risk_score | integer | NULL, CHECK 0~100 | 规则层直接拦截时可为空 |
| decision | varchar(16) | NOT NULL, CHECK in (PASS, BLOCK, MANUAL_REVIEW) | 三态（FR-050） |
| decided_by | varchar(8) | NOT NULL, CHECK in (RULE, AI) | 判定来源，区分是否降级 |
| degraded | boolean | NOT NULL DEFAULT false | |
| ai_invocation_id | bigint | NULL, FK ai_invocations(id) | 追溯 AI 判定理由（NFR-008） |
| status | varchar(16) | NOT NULL DEFAULT 'PENDING', CHECK in (PENDING, RELEASED, KEPT) | 运营处置状态 |
| handled_by | bigint | NULL, FK users(id) | |
| handled_at | timestamptz | NULL | |
| created_at | timestamptz | NOT NULL DEFAULT now() | |

只有 `decision` 为 `BLOCK` 或 `MANUAL_REVIEW` 时落行；`PASS` 不落行，避免正常流量把表打满。`PASS` 枚举值保留是为了 AI 返回值的完整表达。

索引：`(created_at DESC)` 支持近 24h 拦截计数；`(status)` 支持待处理标记计数；`(user_id, created_at DESC)`。

### ai_invocations（FR-053）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | bigserial | PK | |
| purpose | varchar(16) | NOT NULL, CHECK in (RECOMMEND, RISK) | |
| model_id | varchar(128) | NOT NULL | |
| prompt_version | varchar(16) | NOT NULL | 与特征快照共同重建 prompt |
| input_features | jsonb | NOT NULL | 输入特征快照，**不含完整 prompt** |
| raw_output | text | NULL | AI 原始返回，失败时为空 |
| parsed_result | jsonb | NULL | 校验通过后的结构化结果 |
| latency_ms | integer | NOT NULL | |
| degraded | boolean | NOT NULL DEFAULT false | |
| degrade_reason | varchar(64) | NULL | timeout / invalid_json / not_configured / http_error / schema_invalid / id_not_in_whitelist / score_out_of_range |
| user_id | bigint | NULL, FK users(id) | |
| created_at | timestamptz | NOT NULL DEFAULT now() | |

**禁止写入凭证任何片段**（NFR-004）。`degraded=true` 时 `degrade_reason` 必须非空，以 CHECK 强制。

索引：`(purpose, created_at DESC)`。

## 三、统一统计口径 SQL（ADR-008、INV-1、INV-2）

单活动指标，唯一权威写法：

```sql
SELECT c.total_stock,
       c.claimed_count,
       c.total_stock - c.claimed_count                                       AS remaining_stock,
       count(uc.id) FILTER (WHERE uc.status = 'USED')                        AS used_count,
       count(uc.id) FILTER (WHERE uc.status = 'UNUSED'
                              AND uc.expires_at >  now())                    AS active_count,
       count(uc.id) FILTER (WHERE uc.status = 'UNUSED'
                              AND uc.expires_at <= now())                    AS expired_count,
       c.claimed_count::numeric / c.total_stock                              AS claim_rate,
       CASE WHEN c.claimed_count = 0 THEN NULL
            ELSE count(uc.id) FILTER (WHERE uc.status='USED')::numeric
                 / c.claimed_count END                                      AS redeem_rate
  FROM campaigns c
  LEFT JOIN user_coupons uc ON uc.campaign_id = c.id
 WHERE c.id = :cid
 GROUP BY c.id;
```

口径固定点：

- `claim_rate` 分母为 `total_stock`（系统无曝光埋点，CON-005）
- `redeem_rate` 分母为 `claimed_count`；`claimed_count = 0` 时为 NULL，前端显示「—」，避免除零（FR-030 AC-5）
- `expired_count` 由 `expires_at` 实时比较得出，无需任何后台任务（ADR-002）

对账断言，任意时刻必须成立，作为验证 SQL 保留：

```sql
-- INV-1
SELECT count(*) FROM campaigns WHERE claimed_count > total_stock;                      -- 必须为 0
-- INV-2
SELECT c.id FROM campaigns c
  LEFT JOIN user_coupons uc ON uc.campaign_id = c.id
 GROUP BY c.id, c.claimed_count HAVING count(uc.id) <> c.claimed_count;                -- 必须为空
```

第二条同时验证了"每次 `claimed_count` 递增都恰好对应一张券"，即领券事务不存在半途提交。

异常监控指标（FR-031）：

```sql
SELECT count(*) FROM risk_events
 WHERE decision IN ('BLOCK','MANUAL_REVIEW') AND created_at >= now() - interval '24 hours';
SELECT count(*) FROM risk_events WHERE status = 'PENDING';
```

风控窗口计数（FR-050 规则层）：

```sql
SELECT count(*) FROM user_coupons
 WHERE user_id = :uid AND claimed_at >= now() - (:window_seconds * interval '1 second');
```

口径说明：规则层统计的是**成功领取记录**。被拦截的请求不落 `user_coupons`，因此高频攻击在首次拦截后计数不再增长；这不影响 SC-006，因为拦截状态由 `users.risk_blocked` 与 `risk_events` 持续生效，且窗口内的成功记录已足以维持判定。实现阶段需在 `services/risk` 中同时计入窗口内的 `risk_events`，使连续被拦截的请求仍被判为高风险。

## 四、迁移策略

Alembic 单条初始迁移 `0001_init` 建全部五表、约束与索引。后续变更一律新增 revision，不修改历史迁移。启动时执行 `alembic upgrade head`，幂等。

seed（FR-062）独立于迁移，以 `INSERT ... ON CONFLICT (username) DO NOTHING` 实现幂等：四类角色具名账号（`op001`、`user_a`/`user_b`/`user_c`、`verifier001`、`admin001`）+ 批量 `user001` ~ `userNNN`（默认 200，可配）。

## 五、数据保留

演示项目，不做归档与清理。`ai_invocations` 的增长由"不存完整 prompt"控制；`risk_events` 的增长由"仅落 BLOCK/MANUAL_REVIEW"控制。
