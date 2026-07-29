# 前端设计 — 优惠券发放与核销中心

React 19 + Vite + TypeScript + Ant Design 5，单 SPA + 角色路由守卫（ADR-006）。
前端是本项目最大成本项，因此设计目标是**页面数量最少、组件全部取自成品库、不手写表格与表单**。

## 一、路由与信息架构

一个应用承载四类角色，共 7 个页面。共享布局、请求封装、登录态、错误处理，避免四套应用重复实现。

| 路由 | 页面 | 允许角色 | 对应需求 |
|---|---|---|---|
| `/login` | 登录（Mock 用户选择） | 公开 | FR-060 |
| `/coupons` | 领券广场（含 AI 推荐区） | USER | FR-040、FR-003、FR-010 |
| `/my-coupons` | 我的券 | USER | FR-011 |
| `/verify` | 核销台 | VERIFIER | FR-021、FR-020 |
| `/campaigns` | 活动管理 | OPERATOR | FR-001、FR-002、FR-003 |
| `/risk` | 风险标记审核 | OPERATOR | FR-052 |
| `/stats` | 统计面板 | ADMIN、OPERATOR | FR-030、FR-031 |

登录后按角色跳默认页：USER→`/coupons`，VERIFIER→`/verify`，OPERATOR→`/campaigns`，ADMIN→`/stats`。

## 二、权限守卫

```
<RequireRole roles={['USER']}>  →  无 token 跳 /login；角色不符渲染 403 页
```

守卫是**体验层**，不是安全层。真正的授权在后端（FR-061）。前端隐藏入口不构成保护，这一点需在演示时说明，否则"四个角色"会被理解为四个前端页面。

## 三、页面职责

### 领券广场 `/coupons`

两个区块，上下排列：

1. **AI 推荐区**（`GET /api/recommendations`）——卡片列表，每卡展示活动名、面额、品类标签、剩余库存、**推荐理由文本**。`degraded=true` 时在区块标题旁显示一个「规则推荐」标签并附 tooltip 说明 AI 暂不可用。`cold_start=true` 时标题显示「新人推荐」。
2. **全部可领活动**（`GET /api/campaigns/available`）——表格，含"剩余可领 N 次"列。

领取按钮在两个区块内都有，点击后调 `POST /api/coupons/claim`，成功弹出券码 Modal（大字号券码 + 过期时间倒计时）。

**推荐区位于领取动作之上**，这是 ADR-005 的可视化体现：用户先看到推荐与理由，再做领取决定。演示步骤 b 的"领取成功含 AI 推荐理由"由此满足——理由在页面上已存在，而非来自领券响应。

错误映射：`OUT_OF_STOCK`→「库存不足」；`PER_USER_LIMIT_REACHED`→「已达领取上限」；`RISK_BLOCKED`→「操作过于频繁，已被风控拦截」；`RISK_MANUAL_REVIEW`→「账号存在异常，需人工审核，审核通过后请重新领取」。后两者用 Ant Design 的 `notification` 而非 `message`，因为需要更长的阅读时间。

### 我的券 `/my-coupons`

表格 + `display_status` 筛选。券码列可一键复制（核销时需报给核销员）。过期时间列对未过期券显示倒计时。

倒计时到 0 时**自动刷新该行状态**，使 SC-003 的过期演示无需手动刷新页面。这是对 ADR-002 惰性过期的前端配合。

### 核销台 `/verify`

单输入框 + 两步操作，刻意分成两步：

1. 输入券码 → 「查验」（`GET /api/redemptions/{code}`）→ 展示券信息与 `redeemable`
2. 「确认核销」（`POST /api/redemptions`）

分两步的理由：现实中核销员需先确认券有效再执行不可逆操作。同时它让 SC-004 的演示更清晰——第二次点核销时能明确看到「已核销」。

券码输入框自动转大写、过滤 `0O1IL`（券码字符集不含这些字符，ADR-010），减少人工输入错误。

结果区用 Ant Design `Result` 组件：成功绿色、`COUPON_ALREADY_USED` 警告色、`COUPON_EXPIRED` 警告色、`COUPON_NOT_FOUND` 错误色。

### 活动管理 `/campaigns`

表格 + 创建/编辑抽屉表单。

表单要点：
- `validity_minutes` 用带单位选择的数字输入（分钟/小时/天，提交时统一换算为分钟），既满足运营按天填写的习惯，也保留分钟粒度以支持 SC-003 现场演示
- 编辑时 `face_value`、`validity_minutes` 置为 disabled 并附 tooltip 说明原因（ADR-003）
- `total_stock` 编辑时最小值绑定为当前值，前端即阻止调低（后端仍会校验）
- 派生 `status` 用 Tag 三色展示

### 风险标记审核 `/risk`

表格，列含用户、窗口请求数、评分、决策、判定来源（规则/AI）、是否降级、时间、状态。展开行显示 **`ai_reason` 完整文本**。

操作列两个按钮：「解除」「维持」。

这个页面是必做项而非可选：它是三态决策中「人工审核」唯一的可见证据，缺了它，风控的三态在演示中会退化成两态（ADR-007）。

### 统计面板 `/stats`

三层结构：

1. **全局卡片区**（`GET /api/stats/overview`）：活动数、总库存、总领取、总核销，加两个异常指标——近 24h 风控拦截数、待处理标记数。后两者用醒目色，SC-006 演示后会当场跳动。
2. **活动明细表**（逐个 `GET /api/stats/campaigns/{id}`）：领取率、核销率、剩余库存、券的三段划分。两个比率旁放 `Tooltip`，内容直接取后端返回的 `claim_rate_basis` / `redeem_rate_basis`——口径说明不在前端硬编码，避免前后端口径漂移（FR-030 AC-4）。
3. **对账区**（`GET /api/stats/integrity`）：以 `Result` 组件展示 INV-1 / INV-2 校验通过与否。这是把"库存守恒"从文档变成可点击证据的地方。

`redeem_rate` 为 `null` 时显示「—」。

## 四、状态管理

不引入 Redux/Zustand。理由：本项目无跨页共享的复杂状态，唯一全局态是登录用户。

- **全局**：`AuthContext`（user + token），token 存 `localStorage`，启动时用 `GET /api/auth/me` 恢复登录态
- **服务端数据**：各页面局部 `useState` + `useEffect`，或按需引入 TanStack Query。设计上不强制，实现阶段若出现重复的加载/错误样板再引入
- **表单**：Ant Design `Form` 自带状态

## 五、请求封装

单一 `apiClient`：

- 自动附加 `Authorization`
- 401 → 清除本地 token 并跳 `/login`
- 403 → 不跳转，交由页面展示（区分越权与风控两种 403，依据响应体 `code`）
- 统一把后端 `{code, message}` 抛为可判别的错误对象，页面按 `code` 而非 `message` 分支

按 `code` 分支而非 `message`：文案可能调整，`code` 是契约。

## 六、加载 / 空 / 错误态

| 状态 | 组件 |
|---|---|
| 加载 | 表格用 `Table.loading`，卡片区用 `Skeleton` |
| 空 | `Empty`，文案区分"暂无可领活动"与"暂无待处理标记" |
| 错误 | `Alert` type=error + 重试按钮 |
| 推荐降级 | 不视为错误态，正常渲染 + 「规则推荐」标签 |

推荐降级刻意不做成错误态：对用户而言功能是完整的，只是理由由规则生成（FR-041）。

## 七、响应式

演示以桌面为主。断点仅两档：`>=992px` 常规布局；`<992px` 表格横向滚动、卡片单列。不做移动端专门优化。

## 八、构建与部署

Vite 构建静态产物，由 nginx 容器托管，`/api` 反向代理至后端容器（system-architecture.md 第六节）。开发期用 Vite dev server proxy 指向本地后端。
