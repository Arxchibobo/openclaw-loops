# openclaw-loops

> 一套由 **Claude Code (openclaw)** 直接操控并自我验证的自动化系统，覆盖
> Notion `自我管理` 中两大 Loop:
>
> - **Loop 1 · bot 上架**（DOD: 打通产品供需内容，提升源头效率）
> - **Loop 2 · 社媒运营**（DOD: 提高声量、提高付费转化）

## 一分钟上手

```bash
cd bo-work/openclaw-loops
python -m pip install -e .

openclaw doctor                          # 环境/配置体检
openclaw run bot_listing --dry           # 全 8 步 dry-run，不会真实写外部系统
openclaw run social_ops --dry            # 全 4 步 dry-run
openclaw run bot_listing                 # 真跑（带本地 stub adapters）
openclaw run social_ops --step 1         # 只跑某一步
openclaw verify bot_listing.5            # 单步验证（amy/bo 龙虾一致性）
openclaw status                          # 各 loop cursor + 最近运行
openclaw bridge send --channel log --message "hello"
```

每次运行产出在 `reports/<loop>-<mode>-<utc>.md`，可直接贴回 Notion。

## 目录

| 路径 | 作用 |
|---|---|
| `cli/openclaw.py` | 主 CLI（`openclaw` 命令入口） |
| `core/orchestrator.py` | Loop 状态机；调度 step、收集报告 |
| `core/verifier.py` | 验证表达式求值（`metric >= N`、布尔等） |
| `core/state.py` | SQLite 状态持久化 + KV 存储 |
| `core/bridge.py` | wechat ⇄ slack ⇄ 本地队列 信息桥 |
| `core/logger.py` | JSONL 结构化日志（`logs/`） |
| `loops/bot_listing/step1..8` | bot 上架 8 步实现 |
| `loops/social_ops/step1..4` | 社媒运营 4 步实现 |
| `adapters/` | 外部系统对接（SEO / Workshop / 龙虾 / X） |
| `config/openclaw.yaml` | 全部步骤声明 + 验证条件 |

## 卡点 → 模块映射

### Loop 1 · bot 上架

| Notion 卡点 | 解法 | 文件 |
|---|---|---|
| CLAWbo 抓取 | `adapters/seo.py` 抽象，stub 可跑，环境变量切真实 | `loops/bot_listing/step1_seo_scrape.py` |
| bobo 微信提需 | `core/bridge.py` 收口 + `demands.json` 队列 | `step2_demand_intake.py` |
| 人肉审核 | 规则引擎 + LLM 二次校验 + `pending_human` 队列 | `step3_workshop_review.py` |
| 验收人肉 | 4 项自动 check（trigger/screenshot diff/runtime/schema） | `step4_acceptance.py` |
| amy/bo 龙虾不通 | `adapters/lobster.py` 双侧拉取 + diff + reconcile | `step5_publish.py` |
| 微信唯一接口 | bridge 多通道，wechat 不通时不丢消息 | `step8_notify.py` |

### Loop 2 · 社媒运营

| Notion 卡点 | 解法 | 文件 |
|---|---|---|
| 数据清洗不干净 | v2 cleaner: 标准化 + 子串去重 + 同义合并 | `loops/social_ops/step1_kw_calendar.py` |
| 内容生产无持续性 | `production_queue` + 每日目标 + 状态字段 | `step2_content_pipeline.py` |
| 无 X API、noVnc 易断 | `adapters/x_social.py` 健康探针 + 自动通道切换 | `step3_engagement.py` |
| 无每日埋点、KW 不稳 | daily metrics 文件 + KW score 模型 | `step4_analytics.py` |

## 验证模型

每个 step 都实现三种模式：

| 模式 | 含义 | 用途 |
|---|---|---|
| `dry` | 不做副作用，返回合成 metrics | 计划 / CI |
| `run` | 真实执行，写状态 | 流水线 |
| `verify` | 仅读取最近一次状态并重算 metrics | 验收 |

`config/openclaw.yaml` 里每个 step 的 `verify` 表达式由 `core/verifier.py` 求值。
表达式支持 `>= <= == != > <` 与裸布尔键，足以覆盖配置层的判定。

## 测试

```bash
pip install pytest
pytest tests/ -v
```

`tests/test_smoke.py` 跑通就说明：CLI 加载 ok、所有 step 可 dry/run/verify、
两个 loop 端到端不报错。

## 下一步（替换 stub 为真实接口）

1. `adapters/seo.py` → 接 CLAWbo 真实 endpoint（设 `SEO_BASE_URL`）。
2. `adapters/lobster.py` → 配 `AMY_LOBSTER_URL` / `BO_LOBSTER_URL`。
3. `adapters/x_social.py` → 设 `X_API_KEY` 优先 API；否则 `X_NOVNC_URL` 走 noVnc。
4. `core/bridge.py` → `bridge.wechat.enabled: true` + `WECHAT_WEBHOOK`，slack 同理。
5. `loops/bot_listing/step3_workshop_review.py` 接 LLM 二审。
6. `loops/bot_listing/step4_acceptance.py` 接 dows 自动化测试结果回流。
