# USAGE.md — bobooo 怎么用 openclaw-loops

> 目标：你每天早上看一眼，知道哪个 bot 漏了、哪个流程卡了、哪个增长机会没抓。不用写代码，只看结果。

---

## 快速上手（3 条命令）

```bash
cd ~/.openclaw/workspace/projects/openclaw-loops/repo

# 跑一次完整 bot 上架 loop，产出 gap 报告
SLACK_BOT_TOKEN=$(python3 -c "import json; print(json.load(open('/home/lobster/.openclaw/secrets.json'))['SLACK_BOT_TOKEN'])") \
LOBSTER_SLACK_CHANNEL=C0AR3GXL39D \
.venv/bin/openclaw run bot_listing

# 跑一次 social_ops（社媒运营）
.venv/bin/openclaw run social_ops

# 看最近一次 step 的 cursor
.venv/bin/openclaw status
```

每次跑完会在 `reports/` 落盘一份 Markdown 报告，含每步 verify 结果 + 指标。

---

## Loop 是什么

仓库里有 **两个 loop**：

| Loop | 几步 | 干什么 |
|---|---|---|
| `bot_listing` | 8 | seokw 抓取 → 提需求 → workshop 审核 → 验收 → 上架一致性 → 反馈 → 优化 → 通知 |
| `social_ops` | 4 | 核心词汇 + social calendar → 内容生产与发布 → 互动运营 → 流量判断 + 优化 |

每步跑完有个 **verify 表达式**（比如 `keyword_count >= 50`），绿=过，红=卡住，失败会生成真实诊断信号（不是代码 bug，是业务层真的有问题）。

---

## 三方数据怎么对账（核心卖点）

Step 5 `通过上架` 把 **Amy 的 CMS LandingPage** 和 **你的 Notion Bot Database** 用 `bot_id` 主键做 diff：

```
amy=305  bo=230  common=200  only_amy=96  only_bo=30  consistent=False
```

这 4 个数字每天早上你看一眼就行：
- **common 增加** = 健康增长
- **only_amy 增加** = Notion DB 没跟上（你漏登记了）
- **only_bo 增加** = CMS 没跟上（amy 侧卡流程）

跨龙虾通道走 **Slack 文件**：三只龙虾各自把 snapshot JSON 上传到 #claw2claude，adapter 按文件名前缀 `{side}-listings-snapshot*.json` 取最新。

---

## 你日常要做的事

### 1. 看 gap 报告

每次跑完 `openclaw run bot_listing`，看 `reports/bot_listing-run-*.md` 的 step5 部分：

```yaml
- only_amy: 96  ← 需要去 Notion DB 把这些 bot 补上 "art上线" tag
- only_bo: 30   ← 需要查 CMS 为什么没 Synced
```

### 2. Notion 反向补录（只在需要时）

Amy 会把详情表 upload 到 Slack thread（filename `amy-only-gap-*.json`）：

```json
{
  "bot_id": "1767688011",
  "slug_id": "magic-mike-hotbody",
  "bot_name": "Magic Mike HotBody",
  "floor_url": "selfie",
  "first_synced_at": "2026-01-09",
  "url": "https://art.myshell.ai/creative/magic-mike-hotbody"
}
```

你按 floor 分批到 Notion Bot DB，补 `GUI_bot` = `art上线` 标签即可。

### 3. 查 CMS 卡点（only_bo > 0 时）

Amy 跑 CMS 状态核查后 upload `amy-only-bo-cms-status-*.json`：

| cms_status | 含义 | 动作 |
|---|---|---|
| `Edit` | 真卡上架（QA/test 队列） | 去 dows 查 NSFW test backlog |
| `NotFound` | Notion 过度标记（bot 没进 CMS） | 已自动过滤（data/cms_notfound_bot_ids.json） |
| `Synced` 但 env 错位 | test-framely / production-porn | 改 Notion tag（art上线 → test上线 / porn上线）|
| `Deleted` | CMS 已删 | Notion 清理 |

### 4. 让 cron 每天自动刷

已经在跑：
- Amy cron `f0ef6caf-e348-43b8-ae57-37b350bf5098` 每天 02:00 UTC 刷 amy snapshot
- 你的 bo snapshot 是手动跑 `scripts/dump_bo_snapshot.py` 时刷新；要 cron 化很简单：

```bash
# 每天 01:30 UTC 自动 dump + upload 到 Slack thread
openclaw cron add --name bo-snapshot-daily --cron "30 1 * * *" \
  --session isolated --agent main \
  --message "跑 scripts/dump_bo_snapshot.py 并 upload 到 C0AR3GXL39D"
```

（或者直接喊 `汪汪~ 把 bo snapshot 的 cron 建一下`）

---

## 当前剩余卡点 vs 跑通状态

### ✅ 跑通（真·非 stub）

| 步骤 | 状态 | 数据源 |
|---|---|---|
| bot_listing 1 seokw | ✅ 真 | Amy `omni-channel-agent/output/seo_*.json` |
| bot_listing 2 提需求 | ✅ 真 | LLM + bridge 真发 Slack |
| bot_listing 5 上架一致性 | ✅ 真 | 三方 Slack snapshot + bot_id diff |
| bot_listing 6/7/8 反馈/优化/通知 | ✅ 真 | bridge 真发 Slack |
| social_ops 1 calendar | ✅ 真 | Amy seo pipeline 去重 |
| social_ops 2 生产队列 | ✅ 真 | production_queue |
| social_ops 4 流量 | ✅ 真 | daily metrics + KW score |

### ⚠️ 仍用 stub（需要外部系统接口时才切真）

| 步骤 | 当前 | 切真的条件 |
|---|---|---|
| bot_listing 3 workshop 审核 | 规则引擎 + stub LLM | 接 dows 自动化或真 LLM 二审服务 |
| bot_listing 4 验收 | 4 项 check 框架 | 接 dows 自动化审核 |
| social_ops 3 X 互动 | stub（connection_alive=true） | 接 X API key 或稳定 noVnc session |

这 3 个 step 不是"坏"，是"卡在外部接口"，你什么时候给凭证/接口什么时候切真。

---

## 改代码 / 加新功能时

- 代码在 `~/.openclaw/workspace/projects/openclaw-loops/repo/`
- Repo: https://github.com/Arxchibobo/openclaw-loops
- 配置：`config/openclaw.yaml`（改阈值 / 添加 step / 切换 mode）
- pytest: `.venv/bin/python -m pytest tests/ -v`
- push 前一定跑一次 pytest

---

## 快速诊断

```bash
# 看配置是否能加载
.venv/bin/openclaw doctor

# 只跑某一步（调试）
.venv/bin/openclaw run bot_listing --step 5

# 看 cursor（上次跑到哪步）
.venv/bin/openclaw status

# dry run 不真发 bridge
.venv/bin/openclaw run bot_listing --dry
```

---

## 文件速查

| 路径 | 作用 |
|---|---|
| `config/openclaw.yaml` | loop 配置 / verify 阈值 |
| `loops/bot_listing/step{1..8}_*.py` | bot 上架各步 |
| `loops/social_ops/step{1..4}_*.py` | 社媒运营各步 |
| `adapters/lobster.py` | 三方 snapshot diff（step5 核心）|
| `adapters/seo.py` | 接 Amy 的 omni-channel-agent |
| `core/bridge.py` | Slack + wechat 发送 |
| `scripts/dump_bo_snapshot.py` | 从 Notion Bot DB dump bo snapshot |
| `data/cms_notfound_bot_ids.json` | Amy 提供的 CMS NotFound 黑名单 |
| `reports/*.md` | 每次 run 落盘的报告 |
| `INTEGRATION.md` | 外部系统接入文档 |
