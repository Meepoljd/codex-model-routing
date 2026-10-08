# Codex Radar 自适应模型路由

本仓库安装 `routine_worker`、`complex_worker`、`frontier_worker` 通用工程角色。刷新器将登录账号的原生 `model/list` catalog 与 [Codex Radar](https://codexradar.com/) 基准证据相交，可跨模型家族适配任务难度；不会读取认证文件或发起推理请求。

routine 选择不低于最高质量分 70% 的最低分，complex 为 90%，frontier 选择最高分。优先当前 RadarBench：每个接纳的 model/effort 点必须 complete 且使用相同 binding fingerprint，至少需要三个完整候选；未测的新模型不会阻碍其它完整点。当前证据少于三个候选才使用 `https://codexradar.com/data/intelligence-efficiency.json` 的 legacy schema-2 equal/latest 快照，要求至少 30 样本、source 14 天内、point 30 天内。默认只使用 low、medium、high effort，不会自动升级到 xhigh、max、ultra。可靠成本排序同样要求至少 30 个可用 cost samples；当前样本全零时采用 quality-only，不能保证最低费用。该策略是插件启发式，并非官方能力认证。

显式 `gpt6`、`gpt-6`、`GPT-6`、`GPT-6 Astra` 始终表示精确 `gpt-6-astra` 覆盖，不表示动态 frontier；除非 frontier 正好是该模型，否则用平台支持的 exact-model/default-agent override。

完整的计划、委派和可见性说明见[中文插件文档](plugin/README.md)和[English documentation](plugin/README.en.md)。

## 安装与刷新

```bash
git clone git@github.com:Meepoljd/codex-model-routing.git
cd codex-model-routing/plugin
bash install.sh
```

安装器保留已有 root model/effort pin，只接管缺失、先前由本工具写入或可证实为旧托管版本的 profiles；自定义同名文件保留。已确认托管的 Luna/Sol/Astra/Spark/Terra 旧 profiles 会在迁移时备份并移除。Linux systemd user 环境会启用每六小时一次的 refresh timer；运行时位于 `~/.codex/model-routing/`，包含 Radar 依赖，不依赖 checkout 或插件 cache。

```bash
python3 ~/.codex/model-routing/model_router.py --codex-home ~/.codex status
python3 ~/.codex/model-routing/model_router.py --codex-home ~/.codex refresh
systemctl --user status codex-model-routing.timer
```

`status` 显示 `catalogSelection`、实际 `activeProfiles`、证据、来源和新鲜度，以及 current/degraded refresh 状态。刷新失败会保留 last-good profiles 和选择。安装或刷新后须新开 Codex 任务，运行中的会话不会热加载。

可用 `python3 installer.py --codex-home ~/.codex --no-refresh --schedule disable` 关闭 timer；它仅在 timer 与 service 均属于该 home 时停用。开发验证：`python3 -m unittest discover -s tests -v`。
