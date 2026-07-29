# 技术栈 — 优惠券发放与核销中心

## 版本策略（先说明，避免误读）

本文件**只锁定主版本与兼容区间，不锁定 patch 版本**。原因：设计阶段无法确认某个精确 patch 在实现环境中可安装且无冲突，写死一个未验证的数字属于虚构。

精确 pin 在实现阶段第一个任务中生成：执行安装后以 `pip freeze` 结果写入 `src/backend/requirements.txt`，并把实测版本回填到本文件的「实测锁定版本」一节。

本机已实测可用的基础环境：**Python 3.12.3、Docker 29.6.1、Node v20.20.2**。

## 一、后端

| 组件 | 选型 | 版本约束 | 理由 |
|---|---|---|---|
| 语言 | Python | 3.12（实测 3.12.3） | boto3 是 Bedrock 官方文档的默认语言，查任何 Converse API 问题都能直接取到可用示例；受 ASM-002 约束 |
| Web 框架 | FastAPI | `>=0.115,<1.0` | 自动生成 `/docs`（Swagger UI），可直接作为演示界面现场调接口，省掉 Postman；依赖注入天然承载角色权限依赖（FR-061） |
| ASGI 服务 | uvicorn[standard] | `>=0.30,<1.0` | FastAPI 标配 |
| ORM | SQLAlchemy | `>=2.0,<2.1` | 2.0 风格的 `select()` 与显式事务边界，便于精确控制 ADR-001 要求的语句顺序 |
| 驱动 | psycopg（v3，binary） | `>=3.2,<4.0` | PostgreSQL 官方推荐的现代驱动，binary 包免除本机编译依赖 |
| 迁移 | Alembic | `>=1.13,<2.0` | 迁移作为交付物存在，优于手写 `init.sql` |
| 校验 | Pydantic | `>=2.9,<3.0` | FastAPI 2.x 生态；Settings 用 pydantic-settings 从环境变量加载 |
| 配置 | pydantic-settings | `>=2.5,<3.0` | 风控阈值、Bedrock 参数集中于单一 Settings 对象（FR-050 AC-4 的前提） |
| JWT | PyJWT | `>=2.9,<3.0` | 仅需 HS256 签发与校验，PyJWT 足够且依赖最小 |
| AWS SDK | boto3 | `>=1.35,<2.0` | Bedrock Converse API 调用 |
| 测试 | pytest | `>=8.0,<9.0` | |
| 测试客户端 | httpx | `>=0.27,<1.0` | FastAPI `TestClient` 依赖 |

**替代方案与否决理由**：

- Django + DRF —— 被否。ORM 与 Admin 很强，但本项目的核心是精确控制两条 SQL 的顺序与事务边界（ADR-001），Django ORM 的抽象层在这里是阻碍而非帮助；且 Admin 带来的后台页面无法满足四角色的差异化需求。
- Flask —— 被否。需自行拼装校验、依赖注入、OpenAPI，等于手工重建 FastAPI 已有的部分。
- 异步 SQLAlchemy（asyncpg）—— 被否。领券路径上的关键操作是单行热点更新，其吞吐由数据库行锁决定而非由 IO 并发决定（ADR-001 的已知取舍），异步带来的复杂度换不到收益。同步 + uvicorn 多 worker 足够。
- python-jose —— 被否，改用 PyJWT。前者依赖链更重（含 cryptography 全套），而本项目只需要 HS256。

## 二、数据库

| 组件 | 选型 | 版本约束 | 理由 |
|---|---|---|---|
| 数据库 | PostgreSQL | 16.x | 条件 UPDATE 的行级锁 + 唯一约束 + `FILTER` 聚合语法 + `timestamptz`，四者同时满足 ADR-001、ADR-008、NFR-005 |

**替代方案**：

- MySQL 8 —— 并发原语等价（条件 UPDATE 与唯一索引行为一致），仅统计 SQL 的 `FILTER` 需改写为 `SUM(CASE WHEN ...)`。若团队更熟 MySQL，可平移，成本约一个文件。
- SQLite —— **DQ-001 的回退方案**。零外部依赖，且其全局单写者天然使超发不可能。代价：`SQLITE_BUSY`。SC-006（10 秒 50 次）与 FR-070（N+1 并发）都是密集写入，需配 WAL + `busy_timeout` 并加重试。**演示现场因数据库 busy 报错而非因库存不足报错，是最难解释的失败**，故不作为首选。回退时业务代码无需改动（SQL 只用跨库通用语义），仅需改连接串与并发重试策略。
- Redis —— 被否作为库存扣减载体（ADR-001）。

## 三、前端

| 组件 | 选型 | 版本约束 | 理由 |
|---|---|---|---|
| 框架 | React | `^19` | |
| 构建 | Vite | `^6` | 启动与 HMR 快，配置量小 |
| 语言 | TypeScript | `^5.6` | 后端 API 契约以类型表达，减少 `code` 分支写错 |
| UI 库 | Ant Design | `^5` | Table/Form/Statistic/Result/Descriptions 均为成品，避免手写表格与表单——前端是本项目最大成本项（ADR-006） |
| 路由 | React Router | `^7` | |
| 请求 | 原生 fetch 封装 | — | 只需统一附加 token 与错误转换，引 axios 收益不足 |

**替代方案**：

- Next.js —— 被否。无 SEO 与首屏指标需求，SSR 只增加"哪些代码跑在服务端"的心智负担与一个 Node 部署单元（ADR-006）。
- shadcn/ui + Tailwind —— 被否。定制自由度高，但组件需逐个引入并自行组合，前期速度慢于 Ant Design；本项目优先交付速度。
- Redux / Zustand —— 被否。唯一全局状态是登录用户，`Context` 足够（frontend-design.md 第四节）。
- TanStack Query —— 暂不引入，保留为实现阶段的按需选项：若加载/错误样板重复到令人不适，再引入。

## 四、AI 推理

| 项 | 取值 | 说明 |
|---|---|---|
| 服务 | Amazon Bedrock | 初始需求指定 |
| 接口 | **Converse API** | 跨模型统一的消息接口，换模型只改 `modelId`，请求与响应结构不变。演示前一小时能否换模型可能决定成败（ADR-009、D-14） |
| region | `us-east-1` | 由用户提供的 token 解析得出 |
| 认证 | 环境变量 `AWS_BEARER_TOKEN_BEDROCK` | **短期 API key，有效期 12 小时**（CON-002）。过期后替换环境变量并重启即生效，系统不实现自动续期 |
| modelId | 配置项，默认取轻量档模型 | 具体取值待 DQ-003 在真实凭证下验证；推荐与风控共用一个模型 + 两套 prompt |
| 结构化输出 | 不依赖 Bedrock Structured Outputs | prompt 内声明 JSON 结构 + 服务端无条件严格校验（ADR-009）。该特性的模型与区域可用性无法在设计阶段查证 |
| 超时 | 推荐 3s / 重试 1 次；风控 2s / 不重试 | 风控位于领券交易链路上 |

**替代方案**：直接用 `InvokeModel` —— 被否，各家模型请求体格式不同，换模型需重写解析逻辑。

## 五、部署与工具

| 项 | 选型 | 说明 |
|---|---|---|
| 编排 | Docker Compose | `db` + `api` + `web` 三服务，一条命令起（FR-071） |
| 前端托管 | nginx（alpine 镜像） | 托管 Vite 静态产物并反代 `/api` |
| 并发验收 | Python + `concurrent.futures` / `asyncio` | 作为交付物置于 `scripts/`（FR-070）。不引 k6，避免额外二进制依赖 |
| 版本控制 | git | 已 init，远端 `chunxili/aidlc`。**尚无提交**（git 身份未配置，CON-007） |

## 六、目录结构

```
AIDLC/
├─ .aidlc/                    需求、设计、计划、任务
├─ docker-compose.yml
├─ .env.example               全部配置项，无真值
├─ scripts/
│  └─ concurrency_check.py    FR-070 并发验收交付物
└─ src/
   ├─ backend/
   │  ├─ requirements.txt
   │  ├─ Dockerfile
   │  ├─ alembic.ini
   │  ├─ alembic/versions/
   │  ├─ app/
   │  │  ├─ config.py         Settings（单一配置来源）
   │  │  ├─ db.py
   │  │  ├─ models.py
   │  │  ├─ schemas.py
   │  │  ├─ security.py       JWT + 角色依赖
   │  │  ├─ seed.py
   │  │  ├─ main.py
   │  │  ├─ routers/          HTTP 契约层
   │  │  └─ services/         业务规则层
   │  └─ tests/
   └─ frontend/
      ├─ package.json
      ├─ Dockerfile
      └─ src/{pages,components,api,auth}/
```

`services/` 承载全部业务规则且不依赖 FastAPI 特有能力，这是 DQ-002 的对冲：若 ASM-002 不成立需换语言，领域规则可按设计文档直接移植，损失限于框架适配层。

## 七、实测锁定版本

由 T-01 实测安装后回填。环境：Python 3.12.3 / Windows，安装时间 2026-07-29。
完整 pin 见 `src/backend/requirements.txt`（`pip freeze` 产物，47 行）；直接依赖的约束区间见 `src/backend/requirements.in`。

| 组件 | 约束区间 | **实测安装版本** |
|---|---|---|
| fastapi | `>=0.115,<1.0` | **0.141.0** |
| uvicorn[standard] | `>=0.30,<1.0` | 0.52.0 |
| SQLAlchemy | `>=2.0,<2.1` | 2.0.51 |
| psycopg[binary] | `>=3.2,<4.0` | 3.3.4 |
| alembic | `>=1.13,<2.0` | 1.18.5 |
| pydantic | `>=2.9,<3.0` | 2.13.4 |
| pydantic-settings | `>=2.5,<3.0` | 2.14.2 |
| PyJWT | `>=2.9,<3.0` | 2.13.0 |
| boto3 | `>=1.35,<2.0` | 1.43.58 |
| pytest | `>=8.0,<9.0` | 8.4.2 |
| httpx | `>=0.27,<1.0` | 0.28.1 |
| starlette（fastapi 传递依赖） | — | 1.3.1 |

**版本策略的验证结果**：设计阶段刻意未写死 patch 版本是正确的。当时检索到的信息给出 0.136.1 与 0.139.x 两个互相冲突的值，而实测装到的是 **0.141.0**，两者都不是。若按检索结果 pin，T-01 会直接失败。

### 实现阶段新增的两项技术事实

**1. starlette 1.3.1 弃用 TestClient 对 httpx 的使用**，提示改用 `httpx2`。当前 `TestClient` 仍可正常工作（已实测 200 响应），故本阶段不更换。后续任务大量使用 `TestClient`，若告警影响测试输出可读性，再评估迁移到 `httpx2`。记录于此以免后续误判为环境问题。

**2. 数据库不可达时的健康检查耗时**：`create_engine` 增加 `connect_args={"connect_timeout": 3}`（见 `app/db.py`）。实测 `/api/health` 在数据库完全缺失时仍需约 **6.2 秒**返回，原因是 psycopg 对 `localhost` 依次尝试 IPv6 与 IPv4 两个地址，各自等待 3 秒。该延迟仅在数据库不存在时出现，正常部署下不触发，故不再进一步优化（如强制 `hostaddr` 或降低超时）。此为已知取舍，不是缺陷。
