# 追踪矩阵 — 优惠券发放与核销中心

把每项 FR 与关键 NFR 映射到设计章节、数据实体、API、页面与验证方式。
文档缩写：ARCH=`system-architecture.md`，DB=`database-design.md`，API=`api-specification.md`，FE=`frontend-design.md`，TECH=`technology-stack.md`。

## 一、功能需求追踪

| FR | 设计章节 | 数据实体 | API | 页面 | 验证方式 |
|---|---|---|---|---|---|
| FR-001 创建活动 | ARCH §2 `services/campaign` | campaigns | POST /api/campaigns | /campaigns 抽屉表单 | pytest：合法创建后 `claimed_count=0` 且 user_coupons 行数为 0；非法字段 400；非 OP 403 |
| FR-002 编辑活动 | ARCH §2；DB campaigns 字段可变性 | campaigns | PATCH /api/campaigns/{id} | /campaigns（不可变字段 disabled） | pytest：调低库存 409 `STOCK_CANNOT_DECREASE`；改 `face_value` 409 `FIELD_IMMUTABLE` |
| FR-003 活动查询 | ARCH §2；ADR-002 派生状态 | campaigns | GET /api/campaigns、/available、/{id} | /campaigns、/coupons | pytest：`end_at` 已过与库存耗尽的活动不出现在 USER 视图；派生状态与 now() 一致且无后台任务参与 |
| FR-010 领券 | **ARCH §3 时序图**；ADR-001 | campaigns、user_coupons | POST /api/coupons/claim | /coupons | FR-070 并发脚本 + pytest：N+1 不同用户并发恰好 N 成功；限领 1 时第二次 409；失败路径不产生券也不改 `claimed_count` |
| FR-011 我的券 | ARCH §5 数据隔离；ADR-002 | user_coupons | GET /api/coupons/my | /my-coupons | pytest：到期后无需后台任务状态即为已过期；A 看不到 B 的券 |
| FR-014 券码生成 | ADR-010 | user_coupons.code UNIQUE | 内部 | 券码 Modal / 核销台输入框 | pytest：生成 10000 个无重复、无 `0O1IL`、不含可推导信息 |
| FR-020 核销 | **ARCH §3 核销状态机**；ADR-004 | user_coupons | POST /api/redemptions | /verify | pytest：首次成功、重复返回"已核销"且响应体一致；过期券返回"券已过期"；已核销券过期后仍返回"已核销"；并发 20 次仅 1 次成功 |
| FR-021 查验券 | API §5 | user_coupons | GET /api/redemptions/{code} | /verify 第一步 | pytest：连续查询 10 次状态不变；判定口径与 POST 一致 |
| FR-030 统计面板 | **DB §3 统一口径 SQL**；ADR-008 | campaigns、user_coupons | GET /api/stats/campaigns/{id} | /stats 明细表 | pytest：面板数字与直接 SQL 一致；INV-1/INV-2 恒等；`claimed_count=0` 时 `redeem_rate=null` 不报错 |
| FR-031 异常指标 | DB §3 异常监控 SQL | risk_events | GET /api/stats/overview | /stats 卡片区 | 手工 + pytest：SC-006 后拦截计数增量等于被拦请求数；只统计近 24h |
| FR-040 AI 推荐 | ARCH §4；ADR-009 | campaigns、user_coupons、ai_invocations | GET /api/recommendations | /coupons 推荐区 | pytest：非空且理由非空；白名单外 ID 被丢弃；售罄/过期/已领满不出现；零历史用户仍非空；纯读不改状态 |
| FR-041 推荐降级 | ARCH §4 降级矩阵 | ai_invocations | 同上（`degraded` 字段） | /coupons「规则推荐」标签 | pytest：无效凭证下仍非空且 `degraded=true`；断网响应时间不超时间预算；留痕含降级原因 |
| FR-042 Bedrock 封装 | ARCH §4；TECH §4 | ai_invocations | 内部 | — | pytest（mock）：仅改 `modelId` 即换模型；非法 JSON 不抛未捕获异常；评分 150 判非法；风控超时 ≤2s |
| FR-050 风控两层漏斗 | **ARCH §3 时序图前置段**；ADR-005 | user_coupons、risk_events | POST /api/coupons/claim（`risk` 段） | /coupons 错误提示 | pytest：10 秒 50 次第 11 次起拦截且 `ai_invocations` 无对应记录；低频不调 AI；阈值改 3 后第 4 次拦截；N+1 不同用户无人被拦 |
| FR-051 风控降级 | ARCH §4 | risk_events.degraded | 同上 | — | pytest + 手工：凭证失效下领券正常且仍能拦高频；断网跑通 SC-001~006 |
| FR-052 风险标记管理 | ADR-007 | risk_events、users.risk_blocked | GET /api/risk/events、POST /{id}/handle | /risk | pytest：拦截后标记出现；每条可见 `ai_reason`；拦截前后 `claimed_count` 与券数不变；解除后可领；重复处理幂等 |
| FR-053 AI 留痕 | ARCH §7 | ai_invocations | 内部（经 /api/risk/events 暴露 `ai_reason`） | /risk 展开行 | pytest：一次调用一条记录含耗时与 model_id；降级记录 `degrade_reason` 非空；全表无凭证片段 |
| FR-060 登录 | ARCH §5 | users | POST /api/auth/login、GET /me | /login | pytest：四角色各得含正确 role 的 JWT；无 token 401；篡改签名 401 |
| FR-061 权限校验 | **API §10 路由-角色映射表** | users.role | 全部受保护端点 | RequireRole 守卫 | pytest 参数化覆盖 API §10 全表；越权响应体不含目标资源字段 |
| FR-062 批量 seed | DB §4 | users | 内部（启动执行） | /login 用户下拉 | pytest：启动后 ≥200 普通用户；重复 seed 不产生重复 |
| FR-070 并发脚本 | TECH §5 | — | 调用真实 API | — | 执行 `scripts/concurrency_check.py`，N=100 输出成功100/失败1，不变量不成立退出码非 0 |
| FR-071 一键部署 | **ARCH §6 部署拓扑** | — | GET /api/health | — | 全新环境一条命令跑通演示；无凭证时 `status:ok` 且 `ai_configured:false`；仓库无 `.env` |

## 二、非功能需求追踪

| NFR | 设计落点 | 验证方式 |
|---|---|---|
| NFR-001 不超发 | ADR-001；DB `CHECK (claimed_count <= total_stock)` 作为数据库级兜底 | FR-070 脚本 N=100 与 N=1 |
| NFR-002 幂等 | ADR-004 券状态机；FR-052 处置幂等 | 重复核销 4 次逐字节比对 + 并发 20 次 |
| NFR-003 超时/降级 | ARCH §4 降级矩阵；TECH §4 超时分级 | 无效凭证 + 断网两场景各跑 SC-001~006 |
| NFR-004 凭证与数据安全 | ARCH §5；`services/bedrock` 为唯一凭证持有点；ai_invocations 禁写凭证 | 全仓检索凭证特征串；越权用例；日志抽查 |
| NFR-005 时区 | DB 全字段 `timestamptz` | 切换容器时区后过期判定不变 |
| NFR-006 券码不可预测 | ADR-010 | 10000 个券码唯一性与字符集检查 + 生成逻辑人工审查 |
| NFR-007 部署可移植 | ARCH §6；TECH §2 SQLite 回退路径 | 全新环境从零演示 |
| NFR-008 可追溯 | ARCH §7；ai_invocations、risk_events、`used_by` | 任取风险标记追溯评分/依据/降级/处理人 |
| NFR-009 统计一致 | ADR-008；DB §3 口径 SQL 与对账断言 | GET /api/stats/integrity + 逐项核对 |
| NFR-010 可演示 | ADR-003 分钟粒度；FR-050 阈值可配；FR-070 脚本 | 全程不打开数据库客户端演练一遍 |
| NFR-011 性能 | ADR-005 AI 不入交易链路 | 演示流程记录响应时间 |

## 三、不变量落点

| 不变量 | 设计强制点 | 可验证端点 |
|---|---|---|
| INV-1 库存守恒 | 条件 UPDATE + `CHECK (claimed_count <= total_stock)` + 无作废（`claimed_count` 单调） | GET /api/stats/integrity → `inv1_stock_overflow_count` |
| INV-2 券的完全划分 | `status` 两态 + `expires_at` 惰性比较 | GET /api/stats/integrity → `inv2_mismatch_campaign_ids` |
| INV-3 状态两态 | DB `CHECK status IN ('UNUSED','USED')` + 无 `is_expired` 字段 | 表结构即约束 |

## 四、场景到设计的追踪

| SC | 涉及设计 | 现场可验证方式 |
|---|---|---|
| SC-001 库存 1 + 用户 A 领取 | ADR-005 推荐前置 | /coupons 页面先见推荐理由再领取 |
| SC-002 用户 B 失败 | ADR-001 条件 UPDATE | 页面提示"库存不足"；扩展用 FR-070 脚本 |
| SC-003 过期券核销 | **ADR-003 分钟粒度** | 建 `validity_minutes=1` 活动，等 1 分钟，全程不改库 |
| SC-004 幂等核销 | ADR-004 | /verify 两步操作，第二次点核销显示"已核销" |
| SC-005 推荐非空 | ADR-009 白名单 + 降级 | 三态各请求一次 |
| SC-006 高频拦截 | ADR-005 规则层零 AI 调用 | 脚本打 50 次；/stats 拦截计数当场跳动 |
| SC-007 人工审核闭环 | ADR-007 | /risk 页面解除标记后重领成功 |
| SC-008 权限隔离 | API §10 强制表 | 四条越权请求各返回 403 |
| SC-009 全降级演示 | ARCH §4 | 清空凭证后跑完 SC-001~006 |

## 五、设计一致性自检结果

**术语**：`campaign`/活动、`user_coupon`/券、`risk_event`/风险标记、`ai_invocation`/AI 调用记录，四份文档用词一致；未出现"券池""作废""待审核券"等已否决概念。

**状态机**：券 `UNUSED`/`USED` 两态在 DB CHECK、API 响应 `status`、FE `display_status` 三处一致；"已过期"在三处均为派生而非存储。活动 `PENDING`/`ACTIVE`/`ENDED` 仅在 API 与 FE 出现，DB 无该字段，与 ADR-002 一致。风险标记 `PENDING`/`RELEASED`/`KEPT` 三处一致。

**权限**：API §10 的映射表与 FE §1 路由表逐行核对一致；FE 明确声明守卫是体验层、授权在后端。

**数据模型 ↔ API**：API 返回的 `remaining_stock`、活动 `status`、券 `display_status`、`claim_rate`/`redeem_rate` 均为派生值，DB 中无对应列，与 ADR-002、ADR-008 一致，无冗余存储。

**口径**：`claim_rate` 分母=库存、`redeem_rate` 分母=已领取数，在 DB §3 SQL、API §8 响应字段、FE §3 Tooltip 三处一致，且前端口径文案取自后端 `*_basis` 字段，不存在两套文案。

**发现并已修正的不一致**：初稿曾在 API 中设计"审核通过后自动补发券"的端点，与 ADR-007（审核对象是标记、系统不代为补发）冲突，已删除，并在 API §7 显式写明"不存在批准发券接口"。

**遗留待实现阶段处理的一处细节**（已记录，不阻塞门禁）：DB §3 的风控窗口计数仅统计成功领取记录，连续被拦截的请求不会使计数继续增长。`services/risk` 实现时须同时计入窗口内的 `risk_events`，否则被拦用户在窗口内可能重新落回灰区。该项已作为实现要点写入对应任务。

## 六、覆盖结论

22 项 FR、11 项 NFR、3 条不变量、9 个场景全部有设计落点与验证方式，无悬空需求，无未被需求引用的设计元素。
