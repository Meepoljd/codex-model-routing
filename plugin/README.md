# Codex 模型路由插件

[English](README.en.md)

先给出短计划，再决定由 Root 自己处理、交给一个 Worker，还是拆成多个有依赖关系的任务。每项工作按风险和不确定性选择 Luna、Sol 或 Astra；执行期间由 Root 汇报进度，最后整合证据。

## 工作流程

1. **先 plan**：明确目标、完成标准和已知约束，判断拆分是否能改善效率或质量。简单任务一句话即可；计划不额外增加审批步骤。
2. **确定边界和依赖**：列出每项工作的交付物、负责路径、前置结果、负责人和验证方式。共享接口尚未确定时先调查；共享文件由一个 Worker 负责或串行修改。
3. **再选档分配**：轻量搜索和总结由 Root 处理；较大的实现工作即使不适合拆分，也交给一个 Worker。只有相互独立且收益超过协调成本的工作才并行。
4. **实际委派**：调用原生 `spawn_agent`，使用对应角色和最少必要上下文。交接包含已有证据、已做修改、验证结果、任务边界和升级背景。
5. **持续汇报并整合**：Worker 回报阶段成果和阻塞；Root 在主会话更新任务状态与证据，等待必需结果并按依赖顺序整合，完成针对性验证后汇总。

例如，涉及根因未知的缺陷时，可以先安排 Sol 调查。待根因和接口明确，再将边界清楚的实现交给 Luna。不要提前启动依赖调查结果的实现，也不要为了多 Agent 而拆分高度耦合的工作。

## 路由策略

按 Astra → Sol → Luna 顺序评估，高风险条件优先。

| 层级 | 适用工作 |
| --- | --- |
| Astra · `astra_worker` | 明确要求 GPT-6 Astra；多个架构不确定性相互影响、极复杂任务，或有证据的 Sol 多次失败等例外情况 |
| Sol · `sol_worker` | 架构、根因不明、高耦合或高风险、并发与分布式、安全敏感设计、深度性能诊断、破坏性迁移 |
| Luna · `luna_worker` | 常规开发、功能和重构、API/数据模型变更、测试设计、中等复杂度排障、边界清楚的配置修改 |
| Root · 推荐 Luna low | 理解需求、轻量搜索、简单总结、计划和协调；插件不会切换现有 Root 模型 |

提示长度、文件数量和模型新旧不决定升级。“使用 GPT-6”或“使用高档模型”本身不等于指定 Astra。Worker 不自行委派或升级，由 Root 根据证据决定；直接使用 Astra 时说明原因及未经过 Sol 尝试的事实。

## 能看到哪些执行细节

主会话展示的是**计划、任务状态、阶段产出、证据和最终汇总**。Worker 在发现关键事实、完成阶段、遇到阻塞或假设变化时，通过当前环境可用的父会话消息工具回报；Root 转述与任务有关的进展。

| 想看到的内容 | 实际方式与边界 |
| --- | --- |
| 分工与进度 | Root 展示任务、负责 Worker、依赖和已收到的进度；等待超时不代表失败或完成 |
| 关键操作和结果 | Worker 回报文件、命令结果摘要、验证和产物引用；Root 不把计划中的操作当成已执行 |
| 更详细的线程记录 | 支持的客户端可打开 Worker 线程；Codex CLI 可用 `/agent` 切换查看，实际展示依版本而异 |
| 每条工具事件自动出现在主会话 | 本插件没有这项机制；阶段消息需要 Worker 发送、Root 汇总 |
| 完整私有推理 | 不提供；执行记录和解释性摘要不等于模型的内部推理全文 |

客户端线程入口见官方 [Subagents 文档](https://learn.chatgpt.com/docs/agent-configuration/subagents)。工具语义、验证范围，以及与独立 Agents API 事件流的区别，见[可见性能力说明](plugins/model-routing/skills/model-routing/references/worker-visibility.md)。

## 实现原理

这是**提示词驱动的协作策略**，不是拦截请求的确定性路由程序。它由以下部分组成：

- `plugins/model-routing/skills/model-routing/SKILL.md`：计划、拆分、档位判断、交接和 Root 汇报规则；可通过 `$model-routing` 显式调用。
- `agents/*_worker.toml`：声明模型、推理强度、职责边界和阶段回报要求；不能启用运行环境不支持的模型。
- `install.sh` / `uninstall.sh`：注册本地插件市场、安装技能，备份并复制 Worker 配置；卸载时依据备份还原。

插件未实现日志采集服务或独立看板。当前环境暴露哪些工具、客户端展示哪些内容，仍由 Codex 运行时决定。项目指令和明确的用户要求可覆盖插件策略；配置修改需在新任务中加载，不会热切换正在运行的会话。

## 安装与卸载

在仓库根目录执行：

```bash
git clone git@github.com:Meepoljd/codex-model-routing.git
cd codex-model-routing/plugin
bash install.sh
```

安装后新开 Codex 任务，输入 `$model-routing` 使用。脚本复制三个 Worker 到 `~/.codex/agents/`，覆盖前备份；不会覆盖 `~/.codex/AGENTS.md` 或其它 Codex 配置。

仅手动注册技能时：

```bash
codex plugin marketplace add /绝对路径/codex-model-routing/plugin
codex plugin add model-routing@model-routing
```

这两条命令不会执行本仓库安装脚本中的 Worker 复制步骤；完整安装请使用 `install.sh`。

在 `plugin/` 目录运行 `bash uninstall.sh` 卸载。脚本依据最近的匹配备份还原 Worker，安装前不存在的对应文件会被删除；没有匹配备份时保留 Worker 文件。备份位于 `~/.codex/backups/model-routing-plugin-<时间戳>/`。

## 如何 Hack / 扩展

- **改计划和拆分逻辑**：编辑技能的 `Plan before assigning`，同时保持交接字段与 Root 汇报约定一致。不要将“必须先计划”误写成“必须多 Worker”。
- **改档位或模型**：同步编辑 `Tiers` 和对应 TOML；保留风险优先的判断顺序，核对运行时支持的模型和推理强度。
- **改进度展示**：修改 Worker 回报指令与技能的 `Visible progress and integration`。新增日志 UI/API 属于额外实现，不能仅靠描述宣称支持。
- **新增 Worker**：同步修改档位、交接、安装脚本备份/复制，以及卸载脚本还原逻辑。
- **验证**：先检查 Markdown 引用、TOML/JSON 和安装路径一致性。需要运行验证时，在临时配置环境和新会话中检查轻量任务不滥拆、耦合任务只用一个合适 Worker、独立任务按依赖分配，以及阶段回报确实到达 Root。未实测的行为要标明。

不要将个人配置、凭据、hooks、项目路径或会话记录打包进插件。
