# Codex 模型路由插件

此插件为 Codex 提供按任务风险和复杂度选择模型的路由策略，以及 Luna、Sol、Astra 三个 Worker 配置。技能还说明了如何使用 Codex 原生 Agent 委派任务。

## 一键安装

在仓库的 `plugin/` 目录运行：

```bash
bash install.sh
```

安装脚本会将当前目录注册为本地 Codex 插件市场、安装 `model-routing` 技能，并把三个 Worker 配置复制到 `~/.codex/agents/`。如果同名配置已存在，脚本会先备份再替换。安装不会覆盖 `~/.codex/AGENTS.md` 或其它 Codex 配置。完成后请新开一个 Codex 任务以加载技能和配置。

## 手动安装

```bash
codex plugin marketplace add /绝对路径/codex-model-routing/plugin
codex plugin add model-routing@model-routing
```

需要显式启用路由技能时，在 Codex 中使用 `$model-routing`。

## 卸载

```bash
bash uninstall.sh
```

卸载会移除插件和插件市场，并还原安装前的 Worker 配置。安装前不存在的 Worker 文件会被删除。备份保存在 `~/.codex/backups/model-routing-plugin-<时间戳>/`。

## 使用说明

| 层级 | 模型 | 适用范围 |
| --- | --- | --- |
| Astra | `gpt-6-astra` | 明确指定 Astra，或有充分依据需要最高能力处理的极复杂任务 |
| Sol | `gpt-6-sol` | 架构、根因不明、高风险、并发/分布式、安全敏感及深度性能诊断 |
| Luna | `gpt-6-luna` | 常规开发、重构、测试设计、中等复杂度排障和边界清楚的修改 |

Worker 模型是否可用取决于当前 Codex 运行环境。插件提供路由策略和 Worker 默认配置，不会强制改变 Root 模型，也不会切换正在运行的会话。