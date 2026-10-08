# Codex 自适应模型路由

本仓库为 Codex 安装 Luna、Sol、Astra 三档工程 Worker，并根据当前登录账号的原生 `model/list` catalog 自动选择每个已知家族的最新可用版本。任务仍由提示词策略按风险、耦合度和根因不确定性分类；自动刷新只维护模型 ID 与推理强度，不发起推理请求。

当前随包 last-good 默认值是 Luna `gpt-6-luna`/medium、Sol `gpt-6.1-sol`/high、Astra `gpt-6-astra`/high。版本更新时，选择器按数值版本比较（例如 6.10 高于 6.9），并要求模型可见、非 specialty、支持对应 reasoning effort 且没有明确禁用工具能力。未来 Luna/Sol/Astra 同家族版本无需改代码；未知家族不会被自动归类。

完整的计划、委派与可见性说明见[中文文档](plugin/README.md)和[English documentation](plugin/README.en.md)。

## 安装

```bash
git clone git@github.com:Meepoljd/codex-model-routing.git
cd codex-model-routing/plugin
bash install.sh
```

安装器会：

- 保留已有 Root model/effort，把它视为显式 pin；全新配置使用托管 Luna/low，用户后续改动会自动解除托管。
- 用标记块更新 `~/.codex/AGENTS.md`，保留其它段落。
- 只接管缺失、上次由本工具写入，或字节精确匹配本仓库旧版的 Worker；同名自定义配置始终保留。
- 从 `codex app-server` 的 stdio JSON-RPC 获取登录用户 catalog。它不读取或传输 `auth.json`。
- 在 Linux systemd user 环境启用六小时刷新 timer；其它平台保留 portable 手动命令。
- 在 `~/.codex/backups/model-routing-refresh-*` 留下每次变更前的备份。

安装或刷新后需要新开 Codex 任务；已经运行的会话不会热切模型或重新载入 Worker。

## 状态与刷新

```bash
python3 ~/.codex/model-routing/model_router.py --codex-home ~/.codex status
python3 ~/.codex/model-routing/model_router.py --codex-home ~/.codex refresh
```

`catalogSelection` 是 catalog 推荐，`activeProfiles` 是实际生效值；保留的自定义 profile 会显示 `managed: false`。强制 refresh 会重新查询 catalog；失联、超时、空列表、字段异常或缺少任一角色时，当前 profile 和 last-good 状态保持不变。

Linux timer 排错：

```bash
systemctl --user status codex-model-routing.timer
systemctl --user start codex-model-routing.service
journalctl --user -u codex-model-routing.service --since today
```

timer 使用安装时找到的 `codex` 所在目录构造 PATH，并运行 `~/.codex` 内的独立脚本与模板，不依赖仓库 checkout 或插件 cache。
如需关闭自动刷新，可在仓库根目录运行 `python3 installer.py --codex-home ~/.codex --no-refresh --schedule disable`；它只会停用 unit 路径确实属于该 Codex home 的 timer，不会影响其它 home。

## 卸载与开发验证

```bash
cd codex-model-routing/plugin
bash uninstall.sh
```

卸载会停用 timer、移除插件及本工具仍在管理的 profile/策略块，并保留用户改过的同名 profile 与历史备份。

仓库验证：

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖版本排序、hidden/special/未知家族、effort 与显式工具能力、分页与超时、空/失败 last-good、原子回滚、并发锁、自定义配置保留、旧版精确迁移、临时 home 安装幂等和卸载。
