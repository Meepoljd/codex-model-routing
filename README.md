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

## 实现原理

这个插件是**提示词驱动的协作策略**，不是拦截每条请求、自动分类任务的路由代理，也不会修改当前会话的 Root 模型。Root 根据技能里的规则评估任务，然后在需要时调用 Codex 原生 `spawn_agent`，选择 `luna_worker`、`sol_worker` 或 `astra_worker` 并等待结果。Worker 在独立委派上下文中完成分配的工作；Root 负责整合证据并决定是否升级。

实现由三部分组成：

1. **路由技能**：`plugin/plugins/model-routing/skills/model-routing/SKILL.md`。它定义各档适用任务、升级条件、委派要求和会话生效范围。安装插件后，Codex 可发现并使用 `$model-routing`。
2. **Worker 配置**：`plugin/agents/*_worker.toml`。每个文件声明 Agent 名称、模型 ID、推理强度和职责边界。TOML 提供 Worker 的默认值与指令，不会令不可用模型变得可用。
3. **安装脚本**：`plugin/install.sh` 把 `plugin/` 注册为本地插件市场、安装技能，并将 Worker TOML 复制到 `~/.codex/agents/`。覆盖同名文件前会备份。卸载脚本移除插件并尽可能按该备份还原 Worker 文件。

插件规则是提示词，不是运行时强制策略。明确的用户指令、项目级规则和运行环境能力仍可能影响最终选择。配置变更要在新会话中验证，不会热切换已运行会话。

## 如何 Hack / 扩展

建议先在分支中修改，再用临时 `CODEX_HOME` 安装试跑，确认后再合并到自己的主分支。

- **调整任务分档或升级门槛**：编辑技能中的 `Tiers` 和 `Delegation rules`，保持 Astra → Sol → Luna 的评估顺序；新增高档条件时写清楚可核验的触发证据，避免只因任务长或文件多就升级。
- **换模型或推理强度**：编辑对应的 `plugin/agents/<role>.toml` 中的 `model` 和 `model_reasoning_effort`。技能说明、Agent 名称与 TOML 中的 `name` 应保持一致；修改后检查当前 Codex 是否支持该模型 ID 与推理强度。
- **增加一个 Worker 档位**：新增 TOML 配置，随后同步更新技能的档位表、升级路径、安装脚本中的备份/安装逻辑，以及卸载脚本中的还原逻辑。仅新增一个文件不足以让 Root 知道何时委派它。
- **改变安装行为**：修改 `plugin/install.sh` 或 `plugin/uninstall.sh`。保持备份与回滚配对；不要把本机的 `config.toml`、认证信息、hooks、项目路径或会话数据打包进插件。
- **试跑插件**：在新会话中触发 `$model-routing`，用一个轻量任务和一个高风险/架构任务检查路由解释与实际委派是否匹配。检查 Worker 回报是否包含证据、验证结果和未解决问题。不要把仅在技能中描述的委派当成实际执行。

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