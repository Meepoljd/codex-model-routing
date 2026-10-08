# Codex 自适应模型路由插件

[English](README.en.md)

插件先按风险与不确定性规划和分配工作，再通过 Codex 原生 `spawn_agent` 使用 Luna、Sol 或 Astra Worker。独立刷新器从当前登录账号的原生 `model/list` catalog 维护 Worker 的模型 ID；它不读取认证文件，也不发起模型推理。

## 路由与自动选择

按 Astra → Sol → Luna 评估，高风险条件优先：

| 角色 | 工作 |
| --- | --- |
| `astra_worker` | 用户明确选择 GPT-6/Astra；有证据的 Sol 多次失败；多个架构不确定性相互影响；Sol 难以承担的极高失败代价和跨系统复杂度 |
| `sol_worker` | 架构、根因不明、高耦合或高风险、并发与分布式、安全敏感行为、深度性能诊断、破坏性迁移 |
| `luna_worker` | 常规工程、多文件功能和重构、API/数据模型变更、测试设计、中等排障和边界清楚的配置修改 |
| Root | 理解需求、轻量搜索、简单总结、计划、协调与整合 |

提示长度、文件数量和模型新旧不决定升级。`gpt6`、`gpt-6`、`GPT-6` 或 `GPT-6 Astra` 是用户对当前任务的明确选择时路由 Astra；它们出现在文档、引用、状态历史或策略说明中不触发 Astra。

刷新器只识别名称严格符合 Luna、Sol、Astra 的普通公开模型，按数值版本选最新值，并检查所需 reasoning effort。hidden、specialty、未知家族、字段异常和明确工具能力为 false 的条目会被剔除。它能自动跟进已知家族的未来 6.x/7.x 等版本，但不会猜测新的模型家族属于哪个角色。

当前随包 last-good 是：Luna `gpt-6-luna`/medium、Sol `gpt-6.1-sol`/high、Astra `gpt-6-astra`/high。实际值以 `~/.codex/agents/*_worker.toml` 为准，不要从文档复制静态 ID。

## 执行流程与可见性

Root 先说明目标、拆分判断、依赖、负责路径和验证方式。高度耦合的工作交给一个合适 Worker；只有相互独立且收益超过协调成本的工作才并行。交接包含已有证据、修改、验证、边界与升级背景。

Worker 在关键发现、阶段完成、阻塞或假设变化时回报；Root 在主会话展示计划、观察到的状态、证据和最终整合。支持的客户端可打开 Worker 线程，CLI 可用 `/agent`。本插件不复制所有工具事件，也不暴露私有推理。详细边界见[可见性说明](plugins/model-routing/skills/model-routing/references/worker-visibility.md)。

## 安装

```bash
git clone git@github.com:Meepoljd/codex-model-routing.git
cd codex-model-routing/plugin
bash install.sh
```

安装器会合并带标记的全局路由策略并保留 AGENTS.md 其它内容。已有 Root model/effort 被视为显式 pin；全新配置使用托管 Luna/low，用户后续修改会解除托管。同名自定义 Worker 不会被覆盖；只有缺失、上次由工具写入，或精确匹配本仓库旧版的文件会被管理。旧 Spark/Terra 仅在字节精确匹配旧托管文件时备份删除。

Linux 上会尝试启用 systemd user timer，每六小时刷新一次。安装后的运行时位于 `~/.codex/model-routing/`，不依赖 checkout 或插件 cache。其它平台可运行手动命令。安装或刷新后新开任务，现有会话不会热加载。

## 状态、刷新和排错

```bash
python3 ~/.codex/model-routing/model_router.py --codex-home ~/.codex status
python3 ~/.codex/model-routing/model_router.py --codex-home ~/.codex refresh
```

状态中的 `catalogSelection` 是推荐值，`activeProfiles` 是实际 profile；自定义文件显示 `managed: false`。分页、超时、空 catalog、格式异常或角色缺失都会使刷新失败并保持 last-good 配置。

```bash
systemctl --user status codex-model-routing.timer
systemctl --user start codex-model-routing.service
journalctl --user -u codex-model-routing.service --since today
```

如果同名 marketplace 已指向其它路径，安装器会停止并显示检查/修复命令，不会删除或悄悄替换它。插件内容更新后需要使用官方 cachebuster 更新流程重新安装，并在新任务中验证。

## 卸载

```bash
bash uninstall.sh
```

卸载会移除插件、停用 timer、删除仍由工具管理的 profile 和策略块；用户修改或预先存在的自定义 profile 保留。每次写入前的备份位于 `~/.codex/backups/model-routing-refresh-*`。

## 开发验证

```bash
python3 -m unittest discover -s tests -v
```

修改技能后运行 skill `quick_validate.py`，交付插件前运行 `validate_plugin.py`。不要打包个人配置、凭据、hooks、项目路径或会话记录。
