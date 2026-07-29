# 实现任务列表 — 优惠券发放与核销中心

**审阅状态：已认可**

**范围基线**：需求 `.aidlc/requirements/`（22 FR + 11 NFR + 7 CON + 3 INV）；设计 `.aidlc/design/`（6 份）；决策 `.aidlc/plan/design-plan.md`（ADR-001 ~ ADR-010）。

**最近审阅记录**：

| 项 | 内容 |
|---|---|
| 认可日期 | 2026-07-29 |
| 认可来源 | 用户在会话中回复「认可」 |
| 需求基线 | `.aidlc/requirements/` 全 4 份，编号自检通过（22 FR / 11 NFR / 7 CON / 3 INV / 15 US / 9 SC） |
| 设计基线 | `.aidlc/design/` 全 6 份，一致性自检通过；ADR-001 ~ ADR-010 |
| 认可前检查 | 无循环依赖（有向无环，主链 T-01→T-02→T-03→T-04→T-05→T-08→T-09）；14 项任务均有可观察验收标准与验证命令；无空白的阻塞性 `[Reference]`（两处 Bedrock 相关缺口已附官方文档链接，且不阻塞——失败路径已由降级设计覆盖） |
| 未解决风险 | DQ-001 演示环境、DQ-002 团队语言 用户始终未答，按 ASM-001/ASM-002 假设推进；DQ-003 模型可用性待真实凭证验证 |
| 版本控制状态 | **认可时仓库无任何提交**（git 身份未配置，CON-007），基线仅存在于工作区 |

## 依赖总览

```
T-01 骨架与配置
 ├─ T-02 数据模型与迁移
 │   ├─ T-03 认证与权限        ← 全部业务任务的前置
 │   │   ├─ T-04 活动管理
 │   │   │   ├─ T-05 券码 + 领券核心（不含风控）
 │   │   │   │   ├─ T-06 核销
 │   │   │   │   ├─ T-08 风控规则层（接入领券）
 │   │   │   │   │   └─ T-09 风控 AI 灰区 + 风险标记
 │   │   │   │   ├─ T-10 统计与对账
 │   │   │   │   └─ T-12 并发验收脚本
 │   │   │   └─ T-07 Bedrock 封装 + AI 留痕
 │   │   │       ├─ T-09（见上）
 │   │   │       └─ T-11 AI 推荐 + 降级
 │   └─ T-13 一键部署
 └─ T-14 前端 SPA（依赖 T-04~T-11 的 API 全部就绪）
```

主依赖链：T-01 → T-02 → T-03 → T-04 → T-05 → T-08 → T-09。
主要里程碑：**M1** = T-06 完成（领券与核销全链路可用，SC-002/003/004 可验证）；**M2** = T-09 完成（风控三态闭环，SC-006/007 可验证）；**M3** = T-13 完成（一键部署，SC-009 可验证）；**M4** = T-14 完成（六步演示可视化）。

---

## T-01 项目骨架与配置

- [x] 已完成（2026-07-29）

**目标**：建立可运行的 FastAPI 骨架与单一配置来源，锁定实测依赖版本。

**范围**：`src/backend/` 目录结构、`requirements.txt`、`app/config.py`、`app/db.py`、`app/main.py`（仅 `/api/health`）、`.env.example`。
**不包含**：任何业务模型与端点。

**Depends on**：无

**需求引用**：
- `.aidlc/requirements/functional-requirements.md:418`（FR-071 一键部署，本任务只做配置与健康检查部分）
- `.aidlc/requirements/non-functional-requirements.md:30`（NFR-004 凭证仅从环境变量读取）
- `.aidlc/requirements/non-functional-requirements.md:99`（CON-004 技术栈）

**设计引用**：
- `.aidlc/design/technology-stack.md:11`（后端选型与版本约束区间）
- `.aidlc/design/technology-stack.md:88`（目录结构）
- `.aidlc/design/system-architecture.md:126`（安全边界与配置边界：全部可变参数集中于单一 Settings）

**实现要点**：
1. Settings 用 pydantic-settings 从环境变量 + `.env` 加载，字段涵盖：`database_url`、`jwt_secret`/`jwt_algorithm`/`jwt_expire_minutes`、`seed_normal_user_count`、`risk_window_seconds`/`risk_hard_threshold`/`risk_gray_low`/`risk_enabled`、`bedrock_region`/`bedrock_model_id`/`aws_bearer_token_bedrock`/四个超时重试项、`recommend_candidate_limit`/`recommend_result_limit`。
2. Settings 暴露 `ai_configured` 属性（凭证非空判断），供 `/api/health` 与降级判定使用。
3. `.env.example` 列全部配置项且**无真值**；`aws_bearer_token_bedrock` 留空并注释说明是 12 小时短期 key。
4. 安装后以 `pip freeze` 结果 pin 版本写入 `requirements.txt`，并回填 `.aidlc/design/technology-stack.md:122`「实测锁定版本」一节。

**验收标准**：
- AC-1 `GET /api/health` 返回 `{"status":"ok","database":...,"ai_configured":false}`，未配置凭证时 `status` 仍为 `ok`
- AC-2 `.env.example` 中不含任何凭证真值；`git check-ignore .env` 命中
- AC-3 `requirements.txt` 为精确 pin，且 `technology-stack.md:122` 已回填实测版本

**验证命令**：
```
cd src/backend && python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -c "from app.config import get_settings; print(get_settings().ai_configured)"
.venv\Scripts\uvicorn app.main:app --port 8000   # 另开终端 curl /api/health
git check-ignore -v .env
```

**交付物**：`src/backend/{requirements.txt,app/config.py,app/db.py,app/main.py}`、`.env.example`、`technology-stack.md` 版本回填。

### 实现记录（2026-07-29）

**修改文件**：
- 新增 `src/backend/app/__init__.py`、`app/config.py`、`app/db.py`、`app/main.py`
- 新增 `src/backend/requirements.in`（约束区间）、`requirements.txt`（`pip freeze` 精确 pin，47 行）
- 新增 `.env.example`
- 更新 `.aidlc/design/technology-stack.md:122` 实测版本一节

**实测版本**：fastapi 0.141.0、uvicorn 0.52.0、SQLAlchemy 2.0.51、psycopg 3.3.4、alembic 1.18.5、pydantic 2.13.4、pydantic-settings 2.14.2、PyJWT 2.13.0、boto3 1.43.58、pytest 8.4.2、httpx 0.28.1、starlette 1.3.1。

**验证命令与结果**：

| 验证 | 命令 | 结果 |
|---|---|---|
| 依赖安装 | `python -m venv .venv` + `pip install -r requirements.in` | 通过，44 个包安装成功 |
| 配置加载 | `python -c "from app.config import get_settings; ..."` | 通过：`ai_configured=False`、`risk_hard_threshold=10`、`bedrock_region=us-east-1` |
| AC-1 健康检查 | `TestClient(app).get('/api/health')` | 通过：`200 {"status":"ok","database":"unavailable","ai_configured":false}` —— **未配凭证时 status 仍为 ok** |
| AC-2 `.env` 忽略 | `git check-ignore -v .env` | 通过，命中 `.gitignore:2` |
| AC-2 `.env.example` 无真值 | 检索 `bedrock-api-key-\|ASIA\|AKIA` | 通过，无匹配；且该文件未被忽略（应进仓库） |
| AC-2 全仓凭证扫描 | 检索 `bedrock-api-key-YmVk` 于全部 py/md/txt/in/yml/example | 通过，无匹配 |
| AC-3 精确 pin + 回填 | `pip freeze > requirements.txt`，回填 `technology-stack.md:122` | 通过 |

**三条验收标准全部通过。**

**实现过程中的两项发现**（已记入 `technology-stack.md:122` 一节）：

1. **实测装到 fastapi 0.141.0**，而设计阶段检索到的是相互冲突的 0.136.1 与 0.139.x —— 两者都不对。设计阶段刻意不写死 patch 版本的决定得到验证；若按检索结果 pin，本任务会直接失败。
2. **数据库不可达时 `/api/health` 耗时约 6.2 秒**。已加 `connect_args={"connect_timeout": 3}`，但 psycopg 对 `localhost` 会依次尝试 IPv6 与 IPv4，各等 3 秒。该延迟仅在数据库完全缺失时出现，正常部署不触发，作为已知取舍保留，未进一步优化。

**未在本任务验证的项**：`/api/health` 返回 `database:"ok"` 的路径。原因：**本机 Docker 守护进程未运行**（`docker --version` 可用，但 `docker run` 报 `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`，即 Docker Desktop 未启动）。该路径的验证并入 T-02，T-02 本身就必须有可用的 PostgreSQL。**这是 ASM-001 的部分反例：Docker CLI 存在不等于守护进程可用。**

---

## T-02 数据模型与 Alembic 迁移

- [ ] 未完成

**目标**：建立五张表及其全部约束与索引，使三条不变量由数据库强制。

**范围**：`app/models.py`、`alembic.ini`、`alembic/env.py`、`alembic/versions/0001_init.py`。
**不包含**：seed 数据（属 T-03）、任何查询逻辑。

**Depends on**：T-01

**需求引用**：
- `.aidlc/requirements/functional-requirements.md:6`（INV-1/2/3 三条不变量）
- `.aidlc/requirements/non-functional-requirements.md:41`（NFR-005 全字段 timestamptz 存 UTC）
- `.aidlc/requirements/non-functional-requirements.md:61`（NFR-008 审计字段）

**设计引用**：
- `.aidlc/design/database-design.md:18`（五张表完整字段与约束）
- `.aidlc/design/database-design.md:60`（user_coupons，含 `UNIQUE(campaign_id,user_id,seq)`）
- `.aidlc/design/database-design.md:189`（迁移策略）

**实现要点**：
1. `campaigns` 必须含表级 `CHECK (claimed_count <= total_stock)` —— 这是 INV-1 的数据库级兜底，应用层写错时超发会被数据库直接拒绝。
2. `user_coupons` 必须含 `UNIQUE (campaign_id, user_id, seq)` —— 这一行索引就是限领的并发保障（ADR-001）。
3. `user_coupons` 表级 CHECK 保证 `status='USED'` 与 `used_at`/`used_by` 非空三者同步。
4. 不建 `status`（活动）、`remaining_stock`、`is_expired` 字段（ADR-002）。
5. 索引按设计建齐：`code` UNIQUE、`(campaign_id,status)`、`(user_id,claimed_at DESC)`、`risk_events(created_at DESC)`、`(status)`、`ai_invocations(purpose,created_at DESC)`。
6. `ai_invocations` 加 CHECK：`degraded=true` 时 `degrade_reason` 非空。

**验收标准**：
- AC-1 `alembic upgrade head` 在空库上成功建出 5 表，`alembic downgrade base` 可回退
- AC-2 直接 SQL 插入 `claimed_count > total_stock` 被数据库拒绝
- AC-3 直接 SQL 插入重复 `(campaign_id,user_id,seq)` 被拒绝
- AC-4 所有时间列类型为 `timestamp with time zone`
- AC-5 重复执行 `alembic upgrade head` 幂等无报错

**验证命令**：
```
docker compose up -d db
cd src/backend && .venv\Scripts\alembic upgrade head
docker compose exec db psql -U coupon -d coupon -c "\d+ campaigns"
docker compose exec db psql -U coupon -d coupon -c "INSERT INTO campaigns(name,category,face_value,total_stock,claimed_count,start_at,end_at,validity_minutes,per_user_limit) VALUES ('x','FOOD',1,1,2,now(),now()+interval '1 day',60,1);"   # 必须失败
```

**交付物**：`app/models.py`、`alembic/` 全套、`0001_init` 迁移。

---

## T-03 认证、角色权限与用户 seed

- [ ] 未完成

**目标**：JWT 认证 + 后端强制的角色授权 + 幂等批量 seed。

**范围**：`app/security.py`、`app/routers/auth.py`、`app/seed.py`、启动时执行 seed。
**不包含**：前端登录页。

**Depends on**：T-02

**需求引用**：
- `.aidlc/requirements/functional-requirements.md:358`（FR-060 Mock 登录）
- `.aidlc/requirements/functional-requirements.md:372`（FR-061 越权 403）
- `.aidlc/requirements/functional-requirements.md:388`（FR-062 批量 seed）
- `.aidlc/requirements/user-stories.md:143`（SC-008 权限隔离）

**设计引用**：
- `.aidlc/design/api-specification.md:33`（登录与 me 端点）
- `.aidlc/design/api-specification.md:244`（**路由-角色映射强制表**）
- `.aidlc/design/system-architecture.md:126`（安全边界）
- `.aidlc/design/database-design.md:189`（seed 幂等策略）

**实现要点**：
1. 角色授权由**单一依赖工厂**实现（如 `require_roles("OPERATOR")`），不得把角色判断散落在处理函数内部——`api-specification.md:244` 那张表是唯一事实来源。
2. 越权响应体只含 `{code:"FORBIDDEN",message:...}`，**不得泄露目标资源是否存在**。
3. seed 用 `ON CONFLICT (username) DO NOTHING`：具名账号 `op001`/`user_a`/`user_b`/`user_c`/`verifier001`/`admin001` + 批量 `user001`~`userNNN`（`seed_normal_user_count`，默认 200）。
4. JWT 用 PyJWT，HS256，载荷 `sub`/`role`/`exp`。

**验收标准**：
- AC-1 四类角色各能登录并取得含正确 `role` 的 token；`GET /api/auth/me` 可恢复
- AC-2 无 token → 401；篡改签名 → 401
- AC-3 启动后普通用户数 ≥ 200；重复启动不产生重复用户
- AC-4 参数化测试覆盖 `api-specification.md:244` 全表，每条越权组合返回 403
- AC-5 越权响应体不含目标资源任何字段

**验证命令**：
```
cd src/backend && .venv\Scripts\python -m pytest tests/test_auth.py tests/test_permissions.py -v
docker compose exec db psql -U coupon -d coupon -c "SELECT role,count(*) FROM users GROUP BY role;"
```

**交付物**：`app/security.py`、`app/routers/auth.py`、`app/seed.py`、`tests/test_auth.py`、`tests/test_permissions.py`。

---

## T-04 活动管理

- [ ] 未完成

**目标**：活动创建、编辑（库存只增）、按角色查询，活动状态由时间派生。

**范围**：`app/services/campaign.py`、`app/routers/campaigns.py`、`app/schemas.py` 活动部分。
**不包含**：统计指标（T-10）。

**Depends on**：T-03

**需求引用**：
- `.aidlc/requirements/functional-requirements.md:16`（FR-001）
- `.aidlc/requirements/functional-requirements.md:39`（FR-002，含库存只增的理由）
- `.aidlc/requirements/functional-requirements.md:57`（FR-003，含 USER 视图过滤规则）

**设计引用**：
- `.aidlc/design/api-specification.md:51`（活动管理四个端点）
- `.aidlc/design/database-design.md:35`（campaigns 字段与可变性）
- `.aidlc/design/system-architecture.md:27`（`services/campaign` 职责边界）

**实现要点**：
1. 活动状态 `PENDING`/`ACTIVE`/`ENDED` 由 `start_at`/`end_at` 与 `now()` **实时计算**，不落库、不设后台任务（ADR-002）。
2. `PATCH` 的字段白名单：`name`/`category`/`end_at`/`per_user_limit`/`total_stock`；`total_stock` 只增，调低返回 409 `STOCK_CANNOT_DECREASE`；`face_value`/`validity_minutes` 与已开始活动的 `start_at` 返回 409 `FIELD_IMMUTABLE`。
3. `GET /available` 过滤三条件：`ACTIVE` + 有库存 + 该用户未达 `per_user_limit`；附 `my_claimed_count`；**不下发统计与风控字段**。
4. 创建时不写入任何 `user_coupons` 行。

**验收标准**：
- AC-1 合法创建返回 201，`claimed_count=0`，`user_coupons` 新增行数为 0
- AC-2 `total_stock=0`、`end_at<=start_at` 返回 400
- AC-3 不传 `per_user_limit` 落库为 1
- AC-4 调低库存 409；改 `face_value` 409
- AC-5 已过期与售罄活动不出现在 `GET /available`
- AC-6 派生状态与 `now()` 一致，无后台任务参与

**验证命令**：
```
cd src/backend && .venv\Scripts\python -m pytest tests/test_campaigns.py -v
```

**交付物**：`app/services/campaign.py`、`app/routers/campaigns.py`、`tests/test_campaigns.py`。

---

## T-05 券码生成与领券核心

- [ ] 未完成

**目标**：实现不超发、不超限领的领券事务与不可预测券码。**本任务不接入风控**，风控在 T-08 挂入。

**范围**：`app/services/coupon_code.py`、`app/services/claim.py`、`app/routers/coupons.py`（claim + my）。
**不包含**：风控前置（T-08）、推荐（T-11）。

**Depends on**：T-04

**需求引用**：
- `.aidlc/requirements/functional-requirements.md:76`（FR-010，含事务七步与全部错误语义）
- `.aidlc/requirements/functional-requirements.md:106`（FR-011）
- `.aidlc/requirements/functional-requirements.md:119`（FR-014 券码）
- `.aidlc/requirements/non-functional-requirements.md:7`（NFR-001 不超发）
- `.aidlc/requirements/non-functional-requirements.md:48`（NFR-006 券码不可预测）

**设计引用**：
- `.aidlc/design/system-architecture.md:47`（**领券时序图与事务边界**）
- `.aidlc/design/database-design.md:60`（user_coupons 与唯一约束）
- `.aidlc/design/api-specification.md:89`（领券与我的券端点）

**实现要点**：
1. 严格按时序图顺序：条件 UPDATE 扣库存 → 算 `seq` → 限领校验 → 生券码 → 算 `expires_at` → INSERT，**全部在同一事务内**。
2. 条件 UPDATE 判定依据是**受影响行数**，不得先 SELECT 再判断（存在竞态窗口）。
3. `expires_at = min(campaign.end_at, now() + validity_minutes)`，**领取时计算并落库**（ADR-003）；"是否过期"永不落库。
4. 唯一约束冲突（`IntegrityError`）需捕获并转为 409 `PER_USER_LIMIT_REACHED`，事务回滚使 `claimed_count` 的 `+1` 自动撤销，**不写任何补偿逻辑**。
5. 券码：10 位 Crockford Base32，字符集剔除 `0O1IL`，用 `secrets` 模块；唯一冲突重试至多 5 次，**耗尽后整笔失败，不得降级为可预测码**。
6. `GET /my` 的用户过滤强制取 token 的 `sub`，忽略客户端传入的任何 user_id。
7. `display_status` 为派生值。

**验收标准**：
- AC-1 库存 N、**N+1 个不同用户**并发领取，恰好 N 成功、1 失败且 code 为 `OUT_OF_STOCK`；事后 `claimed_count=N` 且券行数=N
- AC-2 `per_user_limit=1` 时同用户第二次返回 409 `PER_USER_LIMIT_REACHED`，`claimed_count` 未变
- AC-3 `per_user_limit=3` 时可领 3 次，第 4 次失败
- AC-4 任一失败路径不产生券行、不改 `claimed_count`
- AC-5 生成 10000 个券码无重复、无 `0O1IL`、不含可推导信息
- AC-6 用户 A 的 `GET /my` 不含用户 B 的券
- AC-7 领券调用链中不存在 Bedrock 调用（本任务尚未接入风控，天然满足；T-08 后需复验）

**验证命令**：
```
cd src/backend && .venv\Scripts\python -m pytest tests/test_claim.py tests/test_coupon_code.py -v
```

**交付物**：`app/services/coupon_code.py`、`app/services/claim.py`、`app/routers/coupons.py`、`tests/test_claim.py`、`tests/test_coupon_code.py`。

---

## T-06 核销（幂等 + 终态优先）

- [ ] 未完成

**目标**：单条条件 UPDATE 实现幂等核销，回查判定按 status 优先。

**范围**：`app/services/redeem.py`、`app/routers/redemptions.py`。

**Depends on**：T-05

**需求引用**：
- `.aidlc/requirements/functional-requirements.md:138`（FR-020，含判定顺序与全部验收）
- `.aidlc/requirements/functional-requirements.md:164`（FR-021 查验）
- `.aidlc/requirements/non-functional-requirements.md:15`（NFR-002 幂等）
- `.aidlc/requirements/user-stories.md:103`（SC-003 过期券核销）
- `.aidlc/requirements/user-stories.md:112`（SC-004 幂等核销）

**设计引用**：
- `.aidlc/design/system-architecture.md:87`（**核销状态机与判定优先级表**）
- `.aidlc/design/api-specification.md:119`（查验与核销端点）

**实现要点**：
1. 核销 SQL 固定为 `UPDATE ... WHERE code=? AND status='UNUSED' AND expires_at > now()`，判定依据受影响行数。
2. `rowcount=0` 时回查，判定顺序**固定为 status 优先、时间其次**：`USED` → `COUPON_ALREADY_USED`（**即使此刻也已过期**）；`UNUSED` 且过期 → `COUPON_EXPIRED`；无记录 → `COUPON_NOT_FOUND`。
3. `GET /{code}` 必须为纯读，其 `reason` 判定与 POST 共用同一函数，避免两套口径。
4. `used_at`/`used_by` 只在成功那一次写入。

**验收标准**：
- AC-1 首次成功；第 2/3/4 次返回 `COUPON_ALREADY_USED` 且响应体逐字节一致
- AC-2 `validity_minutes=1` 的券等待过期后核销返回 `COUPON_EXPIRED`，**全程未修改数据库**
- AC-3 已核销券在过期后再核销返回 `COUPON_ALREADY_USED`（终态优先）
- AC-4 并发 20 次核销同一券码，恰好 1 次成功，`used_at`/`used_by` 只写入一次
- AC-5 `GET /{code}` 连续 10 次状态不变，判定与 POST 一致
- AC-6 USER/OPERATOR/ADMIN 调用核销返回 403

**验证命令**：
```
cd src/backend && .venv\Scripts\python -m pytest tests/test_redeem.py -v
```

**交付物**：`app/services/redeem.py`、`app/routers/redemptions.py`、`tests/test_redeem.py`。

---

## T-07 Bedrock 封装与 AI 留痕

- [ ] 未完成

**目标**：统一的 Converse 调用封装 + 严格输出校验 + 逐次留痕。**不含任何业务语义。**

**范围**：`app/services/bedrock.py`、`app/services/ai_log.py`。
**不包含**：推荐与风控的业务逻辑（T-11、T-09）。

**Depends on**：T-02（需 `ai_invocations` 表）；建议在 T-04 之后进行以便有真实数据构造特征。

**需求引用**：
- `.aidlc/requirements/functional-requirements.md:257`（FR-042 封装）
- `.aidlc/requirements/functional-requirements.md:341`（FR-053 留痕）
- `.aidlc/requirements/non-functional-requirements.md:22`（NFR-003 超时与降级）
- `.aidlc/requirements/non-functional-requirements.md:30`（NFR-004 凭证不外泄）

**设计引用**：
- `.aidlc/design/system-architecture.md:107`（统一封装的固定顺序与校验判定项）
- `.aidlc/design/technology-stack.md:65`（Converse、region、超时分级）
- `.aidlc/design/database-design.md:109`（ai_invocations 字段与 degrade_reason 枚举）

**[Reference]**：Bedrock Converse API 请求与响应结构、bearer token 认证方式，以 boto3 官方文档为准：
- https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-how.html
实现时须核对 `bedrock-runtime` 客户端在使用 `AWS_BEARER_TOKEN_BEDROCK` 时的初始化方式，不得凭记忆书写。

**实现要点**：
1. 固定顺序：构造请求 → 调用 → 解析 → **严格校验** → 写 `ai_invocations` → 返回或抛降级信号。
2. 校验判定项（任一命中即降级）：非 2xx、超时、非法 JSON、必填字段缺失、活动 ID 不在传入白名单内、评分非 0~100 整数。`degrade_reason` 取值限定为设计中列举的 7 个枚举。
3. **不依赖 Structured Outputs 特性**（ADR-009）。
4. 超时与重试从配置读取：推荐 3s/重试 1；风控 2s/不重试。
5. `input_features` 存 jsonb 快照，**不存完整 prompt**；`prompt_version` 与快照共同支持重建。
6. 凭证不得出现在日志、异常消息、`raw_output`、`input_features` 中。
7. 留痕写入失败不阻断主业务，记录告警。
8. 未配置凭证时直接返回降级信号，`degrade_reason='not_configured'`，**不发起网络请求**。

**验收标准**：
- AC-1 仅修改 `bedrock_model_id` 配置即可切换模型，业务代码零改动
- AC-2 mock 返回非法 JSON 时不抛未捕获异常，转为降级信号并留痕
- AC-3 mock 返回评分 150 时判为非法，`degrade_reason='score_out_of_range'`
- AC-4 mock 返回白名单外 ID 时 `degrade_reason='id_not_in_whitelist'`
- AC-5 风控用途实测超时上限 ≤ 2s
- AC-6 未配置凭证时不发起网络请求且留痕 `not_configured`
- AC-7 全库检索 `ai_invocations` 无凭证特征串（`bedrock-api-key-`、`ASIA`）

**验证命令**：
```
cd src/backend && .venv\Scripts\python -m pytest tests/test_bedrock.py -v
docker compose exec db psql -U coupon -d coupon -c "SELECT count(*) FROM ai_invocations WHERE raw_output LIKE '%bedrock-api-key-%' OR input_features::text LIKE '%ASIA%';"   # 必须为 0
```

**交付物**：`app/services/bedrock.py`、`app/services/ai_log.py`、`tests/test_bedrock.py`（含 mock）。

---

## T-08 风控规则层并接入领券

- [ ] 未完成

**目标**：纯 DB 计数的规则层判定，硬阈值直接拦截且零 AI 调用，挂入领券前置。

**范围**：`app/services/risk.py` 规则层部分、领券路径接入。
**不包含**：灰区 AI 调用与风险标记页接口（T-09）。

**Depends on**：T-05

**需求引用**：
- `.aidlc/requirements/functional-requirements.md:280`（FR-050，含三态语义与阈值）
- `.aidlc/requirements/user-stories.md:128`（SC-006 高频拦截）

**设计引用**：
- `.aidlc/design/system-architecture.md:47`（时序图中风控位于**事务之外**的前置段）
- `.aidlc/design/database-design.md:130`（风控窗口计数 SQL 及其口径说明）
- `.aidlc/design/database-design.md:87`（risk_events 字段）

**实现要点**：
1. 风控在**事务外**先行。绝不可把可能触发网络调用的判定包进持有 `campaign` 行锁的事务（ADR-005）。
2. **窗口计数必须同时计入 `user_coupons` 与 `risk_events`**（设计自检遗留项）：仅统计成功领取时，用户被拦截后计数不再增长，可能重新落回灰区甚至放行。计数口径 = 窗口内成功领取数 + 窗口内已记录的风控事件数。
3. 判定：`> hard_threshold` → `BLOCK`（**不调用 Bedrock**）；落在 `[gray_low, hard_threshold]` → 标记为灰区待 T-09 处理，本任务先按保守规则判定；`< gray_low` → `PASS`。
4. `PASS` **不落** `risk_events`，避免正常流量打满表。
5. `BLOCK` 落 `risk_events`（`decided_by='RULE'`）并置 `users.risk_blocked=true`，同一事务内维护一致性。
6. 三阈值与 `risk_enabled` 全部从配置读取。
7. 被拦请求**不占库存、不创建券、不改 `claimed_count`**（ADR-007）。

**验收标准**：
- AC-1 同用户 10 秒内 50 次领取，第 11 次起返回 403 `RISK_BLOCKED`
- AC-2 该场景全程 `ai_invocations` 无新增记录（零 Bedrock 调用），断网亦可复现
- AC-3 低频单次领取不调用 AI，响应时间不受 AI 影响
- AC-4 `risk_hard_threshold` 改为 3 后第 4 次即被拦截，无需改代码
- AC-5 **N+1 个不同用户**并发领取时无人被拦（验证计数维度为 user_id）
- AC-6 拦截前后 `claimed_count` 与券行数均无变化
- AC-7 连续被拦截时窗口计数持续生效，不会因不落 `user_coupons` 而回落至放行

**验证命令**：
```
cd src/backend && .venv\Scripts\python -m pytest tests/test_risk_rule.py -v
python scripts/concurrency_check.py --stock 100   # T-12 完成后复验 AC-5
```

**交付物**：`app/services/risk.py`（规则层）、领券接入、`tests/test_risk_rule.py`。

---

## T-09 风控灰区 AI 判定与风险标记管理

- [ ] 未完成

**目标**：灰区调用 AI 得出评分与三态决策，AI 失败降级为规则；运营可审核风险标记形成闭环。

**范围**：`app/services/risk.py` AI 层与降级、`app/routers/risk.py`。

**Depends on**：T-07、T-08

**需求引用**：
- `.aidlc/requirements/functional-requirements.md:280`（FR-050 灰区与三态）
- `.aidlc/requirements/functional-requirements.md:306`（FR-051 风控降级）
- `.aidlc/requirements/functional-requirements.md:320`（FR-052 风险标记管理）
- `.aidlc/requirements/user-stories.md:134`（SC-007 人工审核闭环）

**设计引用**：
- `.aidlc/design/api-specification.md:176`（风险标记两个端点，含 `ai_reason` 为必需字段）
- `.aidlc/design/system-architecture.md:115`（降级矩阵中的风控行）
- `.aidlc/design/database-design.md:87`（risk_events 与 ai_invocation_id 关联）

**实现要点**：
1. 灰区同步调用一次 AI（2s、不重试）；失败则规则保守判定：接近硬阈值判 `MANUAL_REVIEW`，否则 `PASS`。降级不得使领券整体失败。
2. `MANUAL_REVIEW` 与 `BLOCK` 在当次请求结果上都是失败，**区别在于**：`MANUAL_REVIEW` 产生运营待办且返回 403 `RISK_MANUAL_REVIEW`（文案不同）；`BLOCK` 静默且返回 403 `RISK_BLOCKED`。
3. `ai_reason` 是必需字段而非附加信息：运营看不到判定理由就无从审核。规则层直接拦截时该字段填规则说明文本（如"10 秒内 50 次请求，超过硬阈值 10"）。
4. `RELEASE` → 标记置 `RELEASED` 并清除 `users.risk_blocked`；`KEEP` → 置 `KEPT`。重复处理返回当前状态（幂等）。
5. **不实现"批准发券"**：系统不代为补发，用户走正常领取路径（ADR-007）。

**验收标准**：
- AC-1 风控拦截后 `GET /api/risk/events` 出现对应记录
- AC-2 每条记录 `ai_reason` 非空（AI 判定时为 AI 理由，规则拦截时为规则说明）
- AC-3 拦截或待审核发生前后 `claimed_count` 与券行数均无变化
- AC-4 `RELEASE` 后该用户可成功领取
- AC-5 重复 `handle` 同一标记返回当前状态，不报错
- AC-6 凭证失效下领券正常且仍能拦高频（降级生效）
- AC-7 USER/VERIFIER/ADMIN 调用风险标记接口返回 403

**验证命令**：
```
cd src/backend && .venv\Scripts\python -m pytest tests/test_risk_ai.py tests/test_risk_review.py -v
```

**交付物**：`app/services/risk.py`（AI 层 + 降级）、`app/routers/risk.py`、`tests/test_risk_ai.py`、`tests/test_risk_review.py`。

---

## T-10 统计面板、异常指标与对账端点

- [ ] 未完成

**目标**：实时聚合的统计口径 + 异常指标 + 不变量自检端点。

**范围**：`app/services/stats.py`、`app/routers/stats.py`。

**Depends on**：T-05（需券数据）；T-08（需 `risk_events` 才能出异常指标）

**需求引用**：
- `.aidlc/requirements/functional-requirements.md:179`（FR-030 口径与 AC）
- `.aidlc/requirements/functional-requirements.md:201`（FR-031 异常指标）
- `.aidlc/requirements/non-functional-requirements.md:68`（NFR-009 口径一致）

**设计引用**：
- `.aidlc/design/database-design.md:130`（**统一口径 SQL 与对账断言 SQL，逐字照用**）
- `.aidlc/design/api-specification.md:199`（三个统计端点与 `*_basis` 字段）

**实现要点**：
1. SQL **直接照用** `database-design.md:130` 的写法，不另起口径。
2. `claim_rate` 分母 `total_stock`；`redeem_rate` 分母 `claimed_count`，`claimed_count=0` 时返回 `null`（前端显示「—」），**不得除零也不得返回 0**。
3. 响应必须带 `claim_rate_basis` / `redeem_rate_basis` 文案字段，供前端直接展示，避免前后端口径漂移。
4. **不建预聚合表、不加缓存**（ADR-008）。
5. `GET /api/stats/integrity` 返回 INV-1、INV-2 校验结果，使对账可一键演示。
6. `risk_blocked_24h` 只统计近 24 小时且 `decision IN ('BLOCK','MANUAL_REVIEW')`。

**验收标准**：
- AC-1 面板数字与直接 SQL 查询完全一致（无中间缓存）
- AC-2 `total_stock = claimed_count + remaining_stock` 任意时刻成立
- AC-3 `claimed_count = used + active + expired` 任意时刻成立
- AC-4 `claimed_count=0` 时 `redeem_rate` 为 `null` 且不报错
- AC-5 响应含两个 `*_basis` 口径说明字段
- AC-6 SC-006 执行后 `risk_blocked_24h` 增量等于被拦请求数
- AC-7 `GET /api/stats/integrity` 返回 `ok=true`
- AC-8 VERIFIER 调用统计接口返回 403

**验证命令**：
```
cd src/backend && .venv\Scripts\python -m pytest tests/test_stats.py -v
curl -H "Authorization: Bearer $ADMIN" http://localhost:8000/api/stats/integrity
```

**交付物**：`app/services/stats.py`、`app/routers/stats.py`、`tests/test_stats.py`。

---

## T-11 AI 推荐与降级

- [ ] 未完成

**目标**：确定性召回 + AI 重排 + 白名单校验，降级路径硬保证列表非空。

**范围**：`app/services/recommend.py`、`app/routers/recommendations.py`。

**Depends on**：T-07、T-04

**需求引用**：
- `.aidlc/requirements/functional-requirements.md:219`（FR-040 六步规则）
- `.aidlc/requirements/functional-requirements.md:242`（FR-041 降级）
- `.aidlc/requirements/user-stories.md:121`（SC-005）

**设计引用**：
- `.aidlc/design/api-specification.md:156`（推荐端点与响应约束）
- `.aidlc/design/system-architecture.md:115`（降级矩阵中的推荐行）
- `.aidlc/design/frontend-design.md:32`（推荐区位于领取动作之上）

**实现要点**：
1. 候选集由 SQL 确定性召回：`ACTIVE` + 有库存 + 该用户未领满，取 `recommend_candidate_limit` 条。
2. 用户特征仅来自领券与核销记录（CON-006 数据贫瘠）：领取次数、核销次数、核销率、`category` 偏好分布、面额区间。
3. AI 返回后**逐个校验 ID 在候选白名单内，不在的直接丢弃**（ADR-009）。AI 只能重排，不能造活动。
4. 冷启动（零历史）：按热度（领取率）排序，prompt 显式标注新用户，`cold_start=true`。
5. 降级：热度排序 + 模板理由，`degraded=true` + `degrade_reason`。**列表非空是硬保证，不依赖 AI 可用性。**
6. 纯读接口，不得改动任何状态。
7. 候选集本身为空时返回空数组，属合法状态而非错误。

**验收标准**：
- AC-1 有可领活动时返回非空列表，每项 `reason` 非空
- AC-2 AI 返回白名单外 ID 时该项被丢弃，不出现在响应
- AC-3 已过期、售罄、已领满的活动永不出现
- AC-4 零历史用户仍返回非空且 `cold_start=true`
- AC-5 无效凭证下仍非空且 `degraded=true`，`degrade_reason` 非空
- AC-6 断网时响应时间不超过 3s×(1+1) 预算
- AC-7 调用前后库存与券状态无任何变化
- AC-8 降级发生时 `ai_invocations` 留有记录

**验证命令**：
```
cd src/backend && .venv\Scripts\python -m pytest tests/test_recommend.py -v
```

**交付物**：`app/services/recommend.py`、`app/routers/recommendations.py`、`tests/test_recommend.py`。

---

## T-12 并发验收脚本

- [ ] 未完成

**目标**：一条命令当场证明不超发，并作为回归测试。

**范围**：`scripts/concurrency_check.py`。

**Depends on**：T-05、T-03（需批量用户）

**需求引用**：
- `.aidlc/requirements/functional-requirements.md:404`（FR-070）
- `.aidlc/requirements/non-functional-requirements.md:7`（NFR-001）
- `.aidlc/requirements/user-stories.md:97`（SC-002 扩展验证）

**设计引用**：
- `.aidlc/design/technology-stack.md:79`（用标准库 `concurrent.futures`，不引 k6）
- `.aidlc/design/api-specification.md:224`（可复用 integrity 端点做断言）

**实现要点**：
1. 流程：创建库存 N 的活动 → 取 **N+1 个不同用户** 的 JWT → 并发 N+1 次领取 → 汇总成功/失败数与失败原因 → 校验 `claimed_count=N` 且券行数=N。
2. **必须使用不同用户**：同一用户会被 T-08 风控拦截，导致"成功数远小于 N"而被误判为扣减缺陷。
3. 不变量不成立时以**非 0 退出码**结束。
4. 支持 `--stock N` 与 `--base-url` 参数。

**验收标准**：
- AC-1 `--stock 100` 输出"成功 100、失败 1、失败原因均为 OUT_OF_STOCK"
- AC-2 `--stock 1` 同样通过（对应 SC-002 演示场景）
- AC-3 不变量不成立时退出码非 0
- AC-4 运行过程中无风控拦截产生（验证用了不同用户）

**验证命令**：
```
python scripts/concurrency_check.py --stock 100 --base-url http://localhost:8000
python scripts/concurrency_check.py --stock 1
echo %ERRORLEVEL%
```

**交付物**：`scripts/concurrency_check.py`。

---

## T-13 一键部署

- [ ] 未完成

**目标**：`docker compose up` 起 db + api，缺凭证仍可启动并降级。

**范围**：`docker-compose.yml`、`src/backend/Dockerfile`、启动脚本（迁移 + seed）。
**不包含**：前端容器（并入 T-14）。

**Depends on**：T-02、T-03

**需求引用**：
- `.aidlc/requirements/functional-requirements.md:418`（FR-071）
- `.aidlc/requirements/non-functional-requirements.md:55`（NFR-007）
- `.aidlc/requirements/user-stories.md:152`（SC-009 全降级演示）

**设计引用**：
- `.aidlc/design/system-architecture.md:139`（**部署拓扑与启动序列**）
- `.aidlc/design/technology-stack.md:79`（编排与镜像）

**实现要点**：
1. 启动序列：`db` 健康检查通过 → `api` 执行 `alembic upgrade head` → 执行幂等 seed → 开始服务。
2. 缺少 `AWS_BEARER_TOKEN_BEDROCK` 时**服务必须正常启动**，AI 进入降级；`/api/health` 的 `status` 仍为 `ok`，仅 `ai_configured=false`。
3. `db` 使用命名卷；`pgdata/` 已在 `.gitignore` 中。
4. `.env` 不进镜像、不进仓库。

**验收标准**：
- AC-1 全新环境 `docker compose up -d` 后 `/api/health` 返回 `ok`
- AC-2 无凭证时服务正常启动，核心业务（领券、核销、统计）不受影响
- AC-3 仓库中不存在 `.env` 与任何凭证明文
- AC-4 重复启动幂等，不产生重复 seed 数据
- AC-5 **清空凭证后可完整走通 SC-001 ~ SC-006**

**验证命令**：
```
docker compose down -v && docker compose up -d
curl http://localhost:8000/api/health
git grep -n "bedrock-api-key-" ; git grep -n "ASIA"   # 均应无结果
python scripts/concurrency_check.py --stock 1
```

**交付物**：`docker-compose.yml`、`src/backend/Dockerfile`、入口脚本。

---

## T-14 前端 SPA

- [ ] 未完成

**目标**：7 个页面 + 角色守卫，使竞赛演示六步可视化。

**范围**：`src/frontend/` 全部；`docker-compose.yml` 增加 `web` 服务与 nginx 反代。

**Depends on**：T-04 ~ T-11（API 全部就绪）、T-13

**需求引用**：
- `.aidlc/requirements/user-stories.md:85`（SC-001 ~ SC-009 全部场景）
- `.aidlc/requirements/functional-requirements.md:179`（FR-030 AC-4 口径需在界面上有文字说明）

**设计引用**：
- `.aidlc/design/frontend-design.md:6`（路由与角色表）
- `.aidlc/design/frontend-design.md:30`（七个页面职责，含核销台两步操作、倒计时自动刷新、口径 Tooltip 取自后端字段）
- `.aidlc/design/frontend-design.md:100`（请求封装：按 `code` 而非 `message` 分支）
- `.aidlc/design/api-specification.md:6`（错误码 → 文案映射）

**实现要点**：
1. 领券页**推荐区在领取动作之上**，这是 ADR-005 的可视化体现，也是演示步骤 b 的解释依据。
2. 核销台刻意两步（查验 → 确认核销），使 SC-004 的"已核销"结果清晰可见。
3. 我的券页倒计时到 0 自动刷新该行，配合惰性过期，使 SC-003 无需手动刷新。
4. 统计页口径 Tooltip **直接取后端 `*_basis` 字段**，不在前端硬编码文案。
5. 风险标记页为必做项：它是三态决策中"人工审核"唯一的可见证据。
6. 错误分支按 `code` 判别；`RISK_*` 两态用 `notification` 而非 `message`（需要更长阅读时间）。
7. 券码输入框自动大写并过滤 `0O1IL`。
8. 守卫是体验层，**演示时须说明真正的授权在后端**。

**验收标准**：
- AC-1 四类角色登录后各自默认页正确，越权路由渲染 403 页
- AC-2 竞赛演示六步（SC-001 ~ SC-006）可在界面上完整走通
- AC-3 统计页两个比率旁的口径说明文案来自接口返回值
- AC-4 推荐降级时显示「规则推荐」标签而非错误态
- AC-5 我的券页券到期后自动变为「已过期」，无需手动刷新
- AC-6 `docker compose up` 后可直接访问前端

**验证命令**：
```
cd src/frontend && npm install && npm run build && npx tsc --noEmit
docker compose up -d && start http://localhost:5173
```

**交付物**：`src/frontend/` 全套、`web` 服务定义、nginx 配置。

---

## 待补充的 [Reference]

| 位置 | 缺口 | 处理 |
|---|---|---|
| T-07 | Bedrock Converse 在 bearer token 认证下的客户端初始化方式 | 已附官方文档链接，实现时须核对，不得凭记忆书写 |
| T-07 / T-11 / T-09 | `bedrock_model_id` 的实际可用取值（DQ-003） | 需在真实凭证下做一次连通性验证；失败不阻塞，走降级 |

## 覆盖自检

- 22 项 FR 全部落入 T-01 ~ T-14，无遗漏
- 11 项 NFR 均有对应任务的验收标准承载
- 3 条不变量分别由 T-02（数据库约束）、T-05（领券事务）、T-10（对账端点）三处保障
- 9 个场景 SC-001 ~ SC-009 均可在 T-14 完成后于界面验证，其中 SC-002/003/004/006/007 在 T-12 完成后即可用脚本或 API 验证
- 无循环依赖：依赖图为有向无环，主链 T-01→T-02→T-03→T-04→T-05→T-08→T-09
