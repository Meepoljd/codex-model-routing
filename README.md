# Codex 模型路由插件

本仓库提供一套可安装的 Codex 模型路由插件，按任务类型、风险、耦合度和根因不确定性选择合适的模型，并通过 Codex 原生 Agent 委派工作。

## 先计划，再分配

Root 先给出目标、拆分判断、任务依赖、负责边界和完成标准，再选择自己处理、一个 Worker 或多个 Worker。只有依赖已满足且工作互相独立时才并行；高度耦合的实现由一个合适档位的 Worker 负责。

执行中，Worker 回报阶段成果和阻塞，Root 在主会话展示计划、任务状态、证据及最终汇总。支持的客户端可以打开 Worker 线程查看细节；本插件不实现全量工具日志自动转发，也不展示模型的完整私有推理。

详细流程、可见性边界和扩展方式见[中文文档](plugin/README.md) · [English](plugin/README.en.md)。

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

1. **路由技能**：`plugin/plugins/model-routing/skills/model-routing/SKILL.md`。它定义计划、任务拆分、各档适用任务、升级条件、委派要求和会话生效范围。安装后可显式使用 `$model-routing`。
2. **Worker 配置**：`plugin/agents/*_worker.toml`。每个文件声明 Agent 名称、模型 ID、推理强度和职责边界；Worker 会按约定发送阶段更新。TOML 不会令不可用模型变得可用。
3. **安装脚本**：`plugin/install.sh` 注册本地插件市场、安装技能，并将 Worker TOML 复制到 `~/.codex/agents/`；覆盖同名文件前会备份。卸载脚本移除插件并尽可能按该备份还原 Worker 文件。

## 如何 Hack / 扩展

建议先在分支中修改，再用临时 `CODEX_HOME` 安装试跑，确认后再合并。

- **调整任务拆分或升级门槛**：编辑技能中的 `Plan before assigning`、`Tiers` 和 `Handoff and native execution`。为子任务写明依赖、负责人、交付物及验收证据；不要只因任务长或文件多就升级。
- **换模型或推理强度**：编辑 `plugin/agents/<role>.toml` 中的 `model` 和 `model_reasoning_effort`，并同步技能说明；确认运行环境支持所填值。
- **增加 Worker**：新增 TOML 后，同步更新技能中的分档、依赖分配和交接规则，以及安装脚本的备份/安装逻辑和卸载脚本的还原逻辑。
- **改进度展示**：修改 Worker 的阶段回报指令和技能中的 `Visible progress and integration`。增加自动日志转发或独立看板需要额外实现，不能只通过提示词宣称已支持。
- **改变安装行为**：修改 `plugin/install.sh` 或 `plugin/uninstall.sh`，保持备份和还原逻辑一致。不要打包本机配置、认证信息、hooks、项目路径或会话数据。
- **验证**：检查文档链接、TOML/JSON 和安装路径。需要做运行验证时，在临时配置和新会话中分别检查轻量任务不滥拆、耦合任务有单一负责人、独立任务按依赖分配，并确认阶段消息确实到达 Root；明确标记未实测的项目。

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
