# Codex 模型路由插件

此插件为 Codex 提供按任务风险和复杂度选择模型的策略，以及 Luna、Sol、Astra 三个 Worker 配置。它通过 Codex 原生 Agent 委派工作。

## 实现原理

这是**提示词驱动的协作策略**，不是会拦截请求并自动分类任务的路由程序，也不会更改当前会话的 Root 模型。Root 按路由技能评估任务，在需要时使用 Codex 原生 `spawn_agent` 委派给对应 Worker，并等待结果；Root 汇总证据后再决定是否升级。

- `plugins/model-routing/skills/model-routing/SKILL.md` 定义分档规则、升级条件和委派流程。安装插件后可通过 `$model-routing` 显式调用。
- `agents/*_worker.toml` 为各 Worker 声明名称、模型 ID、推理强度和职责边界。它们是默认配置，不会启用运行环境不支持的模型。
- `install.sh` 注册本地插件市场、安装技能，并将 Worker 配置复制到 `~/.codex/agents/`。覆盖前会备份。
- `uninstall.sh` 移除插件，并依据安装备份还原 Worker 配置。

插件规则是提示词，不是运行时强制策略。项目级规则、明确的用户指令和当前运行环境能力仍会影响模型选择。修改配置后需新开会话，当前会话不会热切换。

## 如何 Hack / 扩展

先在自己的分支修改，并用临时 `CODEX_HOME` 试装，确认后再合并。

- **调整路由规则**：修改 `plugins/model-routing/skills/model-routing/SKILL.md` 的 `Tiers` 和 `Delegation rules`。升级条件应基于风险、耦合度或可核验证据，不应仅因任务长或文件多而升级。
- **更换模型/推理强度**：修改 `agents/<role>.toml` 的 `model` 或 `model_reasoning_effort`，并确认当前 Codex 支持对应值。技能里的模型和角色说明要同步更新。
- **新增 Worker**：新增 TOML 后，还要更新技能中的分档与委派路径，以及安装/卸载脚本里的备份、复制和还原逻辑。
- **改变安装方式**：修改 `install.sh` 或 `uninstall.sh`，并保持备份与还原逻辑匹配。不要把个人 `config.toml`、认证信息、hooks、项目路径或会话数据打包进插件。
- **验证修改**：新开会话，用 `$model-routing` 触发技能；分别检查一个常规任务和一个高风险任务的判断及实际 Worker 委派。确认 Worker 返回证据、验证结果和未解决问题。

## 一键安装

在仓库根目录执行：

```bash
git clone git@github.com:Meepoljd/codex-model-routing.git
cd codex-model-routing/plugin
bash install.sh
```

安装后请新开一个 Codex 任务。脚本不会覆盖 `~/.codex/AGENTS.md` 或其它 Codex 配置。

## 手动安装

```bash
codex plugin marketplace add /绝对路径/codex-model-routing/plugin
codex plugin add model-routing@model-routing
```

需要显式使用路由技能时，在 Codex 中输入 `$model-routing`。

## 卸载

在 `plugin/` 目录运行：

```bash
bash uninstall.sh
```

卸载会移除插件和插件市场，并还原安装前的 Worker 配置。安装前不存在的 Worker 文件会被删除。备份保存在 `~/.codex/backups/model-routing-plugin-<时间戳>/`。