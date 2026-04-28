# INTEGRATION.md — 真实外部系统接入指南

> 本文件说明如何把各 stub adapter 替换为真实接口。
> 不需要改 loop 代码本身，只改 adapter + 环境变量。

---

## 1. SEO Adapter（`adapters/seo.py`）

**当前状态：自动接 Amy-clawd 的 omni-channel-agent 输出，无需配置。**

优先级：HTTP endpoint > 指定 JSON 文件 > Amy 的最新 seo_*.json > dev stub

```bash
# 可选：明确指定 JSON
export SEO_SNAPSHOT_JSON=~/.openclaw/workspace/skills/omni-channel-agent/output/seo_20260427_0259.json

# 未来 CLAWbo daemon 接好后
export SEO_BASE_URL=http://localhost:8765/keywords
```

Amy-clawd 的 omni-channel-agent 每周五 04:00 UTC 产出：
`~/.openclaw/workspace/skills/omni-channel-agent/output/seo_YYYYMMDD_HHMM.json`

---

## 2. Slack Bridge（`core/bridge.py`）

**方案 A：Slack Bot Token（推荐）**

```bash
export SLACK_BOT_TOKEN=xoxb-...   # openclaw bot token
export SLACK_DEFAULT_TARGET=C0AR3GXL39D  # #claw2claude channel id
```

bridge.send("slack", msg) 会走 `chat.postMessage` 直接发到频道。

也可以 per-message 指定 target：

```python
bridge.send("slack", msg, meta={"target": "U07P68KNDUG"})  # DM to bobo
bridge.send("slack", msg, meta={"target": "C0AR3GXL39D"})  # to #claw2claude
```

**方案 B：Webhook（兼容 WeCom/Feishu）**

在 `config/openclaw.yaml` 中启用：
```yaml
bridge:
  slack:
    enabled: true
    webhook_env: SLACK_WEBHOOK
```

```bash
export SLACK_WEBHOOK=https://hooks.slack.com/services/...
```

---

## 3. WeCom/微信 Bridge

```yaml
bridge:
  wechat:
    enabled: true
    webhook_env: WECHAT_WEBHOOK
```

```bash
export WECHAT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...
# WeCom 格式自动识别
```

如果未配置，消息自动入队到 `state/bridge-queue.jsonl`，
大波比 / 人肉接口可手动补发。

---

## 4. Lobster Adapter（`adapters/lobster.py`）
### Amy-clawd (U0AHMSBDV60) ↔ 大波比 (U0AHENJHEDC) 互通

两侧的"bot list state"目前通过 Slack DM 探活确认一致性。

**当 `AMY_LOBSTER_URL` 未配置时（当前状态）：**
- stub 返回空列表，两侧一致 → amy_bo_consistent=True
- Step 5 通过，bot 视为已发布

**未来真实 lobster endpoint 配置：**
```bash
export AMY_LOBSTER_URL=http://amy-clawd-host:8080/lobster/state
export BO_LOBSTER_URL=http://bo-clawd-host:8080/lobster/state
```

协作模式（当前）：
- 大波比 负责 SEO → workshop → 上架决策（Step 1-5）
- Amy-clawd 负责 SEO 数据产出（omni-channel-agent pipeline）
- Lucas-clawd (U0AHW2LEEF3) 负责 landing page / CMS 端对齐

Step 5 的"一致性确认"通过以下协作流完成：
1. 大波比 Run bot_listing step 5 → 产出 publish 列表
2. Bridge.send("slack", notify_msg, meta={"target": "U0AHMSBDV60"}) → Amy-clawd 确认
3. Bridge.send("slack", notify_msg, meta={"target": "U0AHW2LEEF3"}) → Lucas-clawd 对齐 CMS

---

## 5. Workshop Adapter（`adapters/workshop.py`）

当前：规则引擎 (score >= 0.7, forbidden tags) + pending_human 队列。

接 LLM 二审：
```bash
export WORKSHOP_LLM_URL=http://localhost:11434/api/generate  # ollama
# or
export OPENAI_API_KEY=sk-...
export WORKSHOP_LLM_PROVIDER=openai
```

---

## 6. Notion 同步（新增 adapter，待接入）

每个 loop 跑完后自动更新 Notion 的自我管理项目页。

1. 确保 Notion integration `lobster-bot` 已 share 到目标页面：
   `https://www.notion.so/myshellai/3503f81ff51e80a5ae7cc9628f9d3d5e`
2. Integration token 存在 `~/.config/notion/api_key`
3. 跑 `openclaw run bot_listing` — 完成后会自动更新 Notion 状态

Notion page ID: `3503f81f-f51e-80a5-ae7c-c9628f9d3d5e`

> ⚠️ 当前 page 未 share 给 integration，需要 bobooo 在 Notion 里
> 点「...」→「Connect to」→「lobster-bot」共享一下。

---

## 7. X Social（`adapters/x_social.py`）

```bash
# 方案 A: X API
export X_API_KEY=...

# 方案 B: noVnc 浏览器
export X_NOVNC_URL=http://127.0.0.1:18864/vnc.html
```

如两者都未配置，x_social.health() 返回 `{mode: stub, alive: true}` 保持 loop 可运行。

---

## 快速验证

```bash
cd projects/openclaw-loops/repo
.venv/bin/openclaw doctor
.venv/bin/openclaw run bot_listing      # 8/8 should be ok
.venv/bin/openclaw run social_ops       # 4/4 should be ok
.venv/bin/openclaw status
```
