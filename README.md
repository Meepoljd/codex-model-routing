# Codex Model Routing

## Recommended: install the Codex plugin

The current portable package is in [`plugin/`](plugin/). It implements the current Astra → Sol → Luna routing policy and native worker profiles.

```bash
git clone git@github.com:Meepoljd/codex-model-routing.git
cd codex-model-routing/plugin
bash install.sh
```

The installer registers this directory as a local plugin marketplace, installs the `model-routing` skill, and backs up/replaces the three worker profiles in `~/.codex/agents/`. It leaves `~/.codex/AGENTS.md` and unrelated Codex configuration untouched. Start a new Codex task after installation. See [`plugin/README.md`](plugin/README.md) for manual setup and uninstall steps.

## Legacy standalone configuration installer

The root-level `install.sh` and policy below are retained for compatibility with the earlier Spark/Terra-based setup. They are not the recommended current package; use the plugin above for the maintained Astra/Sol/Luna routing policy.

---

# Earlier portable configuration package

这个旧版安装器会配置一套 Codex 模型路由策略：根代理默认使用 Luna，按任务风险路由到 Spark、Terra、Sol 或 Astra。它不会复制机器或项目相关配置，例如 `projects` 信任记录、本地路径、插件缓存、认证信息、hooks 状态或会话数据。

## 模型与推理强度（旧版）

| 角色 | 模型 | 推理强度 |
| --- | --- | --- |
| root | `gpt-5.6-luna` | `low` |
| spark_worker | `gpt-5.3-codex-spark` | `low` |
| terra_worker | `gpt-5.6-terra` | `medium` |
| sol_worker | `gpt-5.6-sol` | `high` |
| astra_worker | `gpt-6-astra` | `high` |

## 前提条件

- Python 3.11 或更高版本（使用标准库 `tomllib`）。
- 一个可写的 Codex home；默认是 `~/.codex`。请先停止依赖同一配置文件的外部编辑器。

## 安装与检查

克隆仓库后进入根目录：

```bash
git clone git@github.com:Meepoljd/codex-model-routing.git
cd codex-model-routing
```

先查看将发生的改变：

```bash
./install.sh --codex-home /path/to/.codex --dry-run
```

确认后安装：

```bash
./install.sh --codex-home /path/to/.codex
```

省略 `--codex-home` 时使用 `~/.codex`。安装器会验证已有 `config.toml`，仅合并根级 `model`、`model_reasoning_effort` 和 `[agents].enabled`，保留其余 TOML 内容及注释；然后复制四个受管 worker 文件，并在 `AGENTS.md` 写入或替换 `Model Routing Policy` 章节。重复运行不会叠加策略块。

每次确实修改前，安装器会在目标目录创建唯一的 `codex-model-routing-backup-...` 备份目录，其中包含每个被替换文件的原始版本和 `manifest.json`。清单对新增文件标记为 `null`。若配置语法无效、目标是符号链接、或预期文件路径是目录，安装器会在写入前失败。少见且不能安全保留语义的 TOML 布局也会被拒绝。

## 回滚

关闭 Codex 后，将最近一次备份目录中对应文件复制回 Codex home 的同一路径；例如将备份中的 `config.toml`、`AGENTS.md` 和 `agents/` 内容还原。查看 `manifest.json`：值为 `null` 的路径在安装前不存在，可手动删除对应的新增文件。

配置和文档只能影响之后启动的会话，**不会切换正在运行的 Codex 会话模型**。

路由策略是给 Codex 的提示词和 worker 默认值，并不是一个会在运行时确定性分类任务的程序；明确选择的用户模型仍优先。

## 测试

```bash
python3 -m unittest discover -s tests -v
```
