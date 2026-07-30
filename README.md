# 优惠券发放与核销中心

SRC-G AI-DLC Workshop 项目。运营创建优惠券活动，用户领取，核销人员核销，管理员监控；
AI 提供个性化推荐与异常检测，且**AI 不可用时功能不缺失，仅降级**。

按 AIDLC 五步法交付，全过程产物在 `.aidlc/`。

## 快速开始

### 方式一：docker compose（推荐用于演示）

```bash
cp .env.example .env          # 按需填入 AWS_BEARER_TOKEN_BEDROCK，留空则 AI 降级
docker compose up -d
```

- 前端 http://localhost:5173
- 接口文档 http://localhost:8000/docs （可直接在此页调用接口做演示）
- 健康检查 http://localhost:8000/api/health

### 方式二：本机原生运行（无需 Docker）

前提：PostgreSQL 16 已运行，且存在 `coupon` 角色与 `coupon` 数据库。

```powershell
# 后端
cd src/backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\uvicorn app.main:app --port 8000 --workers 4

# 前端（另开终端）
cd src/frontend
npm install
npm run dev
```

启动时会幂等 seed 用户，无需手工建账号。

## 演示账号

| 账号 | 角色 | 用途 |
|---|---|---|
| `op001` | 运营 | 创建/编辑活动、审核风险标记 |
| `user_a` / `user_b` / `user_c` | 普通用户 | 演示步骤 b / c / f |
| `verifier001` | 核销员 | 演示步骤 d、e |
| `admin001` | 管理员 | 统计与异常监控 |
| `user001` ~ `user200` | 普通用户 | 并发验收需要 N+1 个不同用户 |

登录只需用户名，无密码（Mock 认证，需求 4.7）。

## 一键验收

两个脚本都打真实服务，不使用 mock、不修改数据库，失败以非 0 退出码结束。

```bash
# 库存不超发：库存 N，N+1 个不同用户并发领取，恰好 N 成功
python scripts/concurrency_check.py --stock 100

# 竞赛演示六步 + 过期核销 + 对账 + 权限隔离
python scripts/demo_check.py
```

`concurrency_check.py` 必须用不同用户：同一用户会被风控按 `user_id` 拦截，
那会让成功数远小于 N 而被误判为库存扣减缺陷。

### 单元与集成测试

```powershell
cd src/backend
.\.venv\Scripts\python -m pytest tests/ -q
```

## 演示流程（对应竞赛评比文档）

| 步骤 | 操作 | 预期 |
|---|---|---|
| a | `op001` 创建库存为 1 的活动 | 创建成功，**不预生成任何券** |
| b | `user_a` 在领券广场领取 | 成功；**页面上方的 AI 推荐区已给出推荐理由** |
| c | `user_b` 领同一活动 | 失败：库存不足 |
| d | `verifier001` 在核销台查验并核销 | 成功 |
| e | 再次核销同一券码 | 返回「已核销」，多次结果一致 |
| f | `user_c` 10 秒内 50 次领取 | 第 11 次起拦截；管理员面板拦截计数当场跳动 |

**过期券核销**：创建"领取后有效 1 分钟"的活动，领取后等 1 分钟再核销，返回「券已过期」。
全程不碰数据库 —— 过期是系统真实行为。

### 演示时需要主动说明的两处

竞赛文档的字面描述与本项目实现有两处有意偏差：

1. **步骤 b「领取成功含 AI 推荐理由」**：推荐由独立接口在**领取之前**生成。
   讲法：把 AI 放在用户决策之前，核心交易链路零 AI 依赖。
2. **步骤 d「用户 A 核销」**：实际由**核销人员**执行，用户仅出示券码。
   项目已排除支付结算，用户自助核销属纯自毁操作；核销之所以存在，是因为线下有人验券。

## 设计要点

三条不变量由**数据库约束强制**，不靠应用层自觉：

- **INV-1 库存守恒**：`total_stock = claimed_count + 剩余库存`，`claimed_count` 单调递增。
  `campaigns` 上有 `CHECK (claimed_count <= total_stock)` 作为兜底 —— 应用层写错时超发会被数据库直接拒绝。
- **INV-2 券的完全划分**：`claimed_count = 已核销 + 未核销未过期 + 未核销已过期`。
- **INV-3 状态两态**：`status` 只有 `UNUSED` / `USED`，"已过期"是 `expires_at <= now()` 的实时判断，不落库。

`GET /api/stats/integrity` 可一键校验 INV-1 与 INV-2，让不变量成为可点击的证据。

其余关键决策：

- **并发全部下沉数据库**：库存用条件 `UPDATE ... WHERE claimed_count < total_stock`，
  限领用 `UNIQUE(campaign_id, user_id, seq)`。应用层不写任何锁。唯一冲突触发回滚时库存的 `+1` 自动撤销，无补偿逻辑。
- **核销幂等键就是券码**：单条条件 UPDATE，`rowcount=0` 时回查并**按 status 优先**判定原因。
  已核销的券过期后再核销返回「已核销」（终态优先）—— 返回「券已过期」会误导核销员以为该券未被使用。
- **AI 与交易链路解耦**：推荐是独立只读接口；风控两层漏斗，硬阈值直接拦截且不调用 Bedrock，仅灰区调 AI。
- **AI 输出不信任**：不依赖 Bedrock Structured Outputs，服务端严格校验，活动 ID 必须落在候选白名单内。
- **人工审核的对象是风险标记，不是待批领取**：被拦请求不占库存。否则风控会沦为拒绝服务工具。

完整设计见 `.aidlc/design/`，决策理由见 `.aidlc/plan/design-plan.md` 的 ADR-001 ~ ADR-010。

## 配置

全部配置项见 `.env.example`。演示现场常用：

| 变量 | 默认 | 说明 |
|---|---|---|
| `AWS_BEARER_TOKEN_BEDROCK` | 空 | Bedrock API key。**短期 key 有效期 12 小时**，过期换新值重启即生效。留空则 AI 降级 |
| `BEDROCK_MODEL_ID` | Claude 3.5 Haiku | 换模型只改此项，不改代码 |
| `RISK_HARD_THRESHOLD` | 10 | 窗口内请求数达到该值即硬拦截 |
| `RISK_GRAY_LOW` | 5 | 灰区下界，落入灰区才调用 AI |
| `RISK_WINDOW_SECONDS` | 10 | 风控时间窗口 |

`.env` 已被 `.gitignore` 排除，凭证不得进入仓库、日志、错误响应或演示截图。

## AI 降级

缺少凭证或断网时：

- 推荐降级为热度排序 + 模板理由，`degraded=true`；**列表非空是硬保证**
- 风控降级为规则引擎；高频拦截能力与 AI 无关
- 服务照常启动，`/api/health` 的 `status` 仍为 `ok`，仅 `ai_configured=false`

因此**清空凭证后仍可完整走通演示六步**。这不是保险措施 —— 需求 6 本身就要求"AI 不可用时降级为规则引擎"。

## 不做的事

金额结算与支付对接、券作废、注册与密码体系、优惠券转赠、多活动叠加规则、消息通知、Redis、异步任务队列、预聚合统计表。
