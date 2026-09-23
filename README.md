# Codex 模型路由插件

本仓库提供一套可安装的 Codex 模型路由插件，按任务类型、风险、耦合度和根因不确定性选择合适的模型，并通过 Codex 原生 Agent 委派工作。

## 路由策略

按以下顺序评估；高风险规则优先于低成本规则。

| 层级 | 模型与 Agent | 适用任务 |
| --- | --- | --- |
| Astra | `gpt-6-astra` · `astra_worker` | 用户明确要求 GPT-6 Astra；极复杂的端到端任务；多个架构问题相互影响；有证据表明 Sol 多次未能解决；或跨系统复杂度和失败代价高到 Sol 难以胜任 |
| Sol | `gpt-6-sol` · `sol_worker` | 架构决策、根因不明、高风险或高耦合任务、并发与分布式问题、安全敏感设计、深度性能诊断、破坏性迁移，或 Luna 多次尝试失败 |
| Luna | `gpt-6-luna` · `luna_worker` | 常规开发、多文件功能和重构、API 或数据模型调整、测试设计、中等复杂度排障及边界明确的配置修改 |
| Root | `gpt-6-luna` · `low` | 理解需求、轻量搜索、简单总结和低风险规划；较大的实现任务委派给对应 Worker |

不要根据提示长度、文件数量或模型新旧决定升级。通用的 GPT-6 请求按任务类型路由至 Sol 或 Luna；只有明确指定 GPT-6 Astra 才直接选择 Astra。安全、架构和并发任务通常由 Sol 处理。

## 一键安装

```bash
git clone git@github.com:Meepoljd/codex-model-routing.git
cd codex-model-routing/plugin
bash install.sh
```

安装脚本会将 `plugin/` 注册为本地 Codex 插件市场、安装 `model-routing` 技能，并把三个 Worker 配置安装到 `~/.codex/agents/`。替换同名配置前会备份原文件。脚本不会覆盖 `~/.codex/AGENTS.md` 或其它 Codex 配置。

安装后新开一个 Codex 任务以加载技能和 Worker 配置。模型是否可用取决于当前 Codex 运行环境；插件不会强制切换正在运行的会话或更改 Root 模型。

## 卸载

在 `plugin/` 目录运行：

```bash
bash uninstall.sh
```

卸载会移除插件与本地插件市场，并根据安装时的备份还原 Worker 配置。备份保存在 `~/.codex/backups/model-routing-plugin-<时间戳>/`。