---
name: gangjing-review
homepage: https://github.com/agent-dance/harness-engineering/tree/main/skills/gangjing
description: >
  Searchable registry-safe alias of gangjing. A contrarian review and red-team
  skill for product, architecture, and code decisions. Defaults to oral review;
  upgrades to code attack only on explicit request or strong assertions about
  current-workspace code.
requires:
  anyBins:
    - python3
    - python
    - node
---

# Gangjing Review

这是 `gangjing` 的 searchable / registry-safe alias。

默认动作：

- 反问
- 拆假设
- 举反例
- 做 pre-mortem
- 给整改建议

升级动作：

- 读取当前工作区代码
- 生成 `attack_config.json`
- 从 `templates/attack-engine-kit.md` 落地临时 harness
- 运行攻击引擎并解释结果

升级条件：

- 用户明确要求测试代码
- 或用户对当前工作区代码做出“绝对没问题”“不可能出错”这类强断言

安全边界：

- 只攻击当前工作区 / 当前仓库里的代码
- 不得指向 `~`、系统目录、凭证目录、SSH 密钥目录，或工作区外路径
- 首次响应先做口头审查，不能直接跑脚本
- 能隔离就隔离：容器、VM、临时工作树、低权限沙箱优先

运行方式：

1. 生成 `attack_config.json`
2. 从 `templates/attack-engine-kit.md` 落地 `.gangjing-tmp/harness.py` 或 `.gangjing-tmp/harness.js`
3. 运行临时 harness
4. 用结果里的 `CRASHED / WRONG / LEAKED` 作为论据给出裁决

如果你需要完整资料、参考文档和仓库内 canonical engine，请看：

- `skills/gangjing/`
- `tooling/gangjing-engine/`
