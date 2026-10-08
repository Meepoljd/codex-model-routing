# Codex Radar 自适应路由插件

[English](README.en.md)

插件安装 `simple_worker`、`routine_worker`、`complex_worker`、`frontier_worker` 通用角色，将登录账号原生 `model/list` catalog 与 [Codex Radar](https://codexradar.com/) 证据相交，可跨模型家族动态选择。simple 选择不低于最高质量分 40% 的最低分，routine 为 70%，complex 为 90%，frontier 为最高分。未刷新时随包 simple fallback 是 `gpt-5.6-terra`/low；刷新后以评测和 native catalog 为准。当前 RadarBench 仅接纳 complete 且同一 binding fingerprint 的 model/effort 点，至少三个完整候选才使用；未测新模型不阻碍其它完整点。覆盖不足时使用 legacy schema-2 equal/latest 快照，要求至少 30 样本、source 14 天内、point 30 天内。这是插件启发式，不是官方能力认证。

默认只自动选择 low、medium、high effort，不会升级到 xhigh、max、ultra。可靠成本排序也要求至少 30 个可用 cost samples；样本全零时采用 quality-only，不承诺最便宜。显式 `gpt6`、`gpt-6`、`GPT-6`、`GPT-6 Astra` 始终指定 `gpt-6-astra`，不会映射动态 frontier。

```bash
bash install.sh
python3 ~/.codex/model-routing/model_router.py --codex-home ~/.codex status
python3 ~/.codex/model-routing/model_router.py --codex-home ~/.codex refresh
```

状态显示选择、实际 profiles、证据/新鲜度和 current/degraded refresh 状态。失败保留 last-good 配置。运行时包含 Radar 依赖且不依赖 checkout；已有 root 配置保持 pin，自定义旧角色保留，已确认托管的旧角色会备份并迁移。刷新后请新开任务。
