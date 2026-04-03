# harness-engineering

这个仓库用于维护可公开分发的 agent skills，目前收录：

- `gangjing`：把“杠精式反对意见”变成建设性的方案审查和代码攻击流程。

## 仓库结构

- `skills/`：每个 skill 一个独立目录。
- `scripts/publish-hubs.mjs`：统一验证并发布到 `skills.sh` / `ClawHub`。
- `skills/publish-manifest.json`：每个 skill 的发布元数据。
- `.github/workflows/publish-skills.yml`：推送到 `main` 后的自动化发布流水线。

## 本地验证

```bash
npm run validate:skills
```

## 手动发布

```bash
# 只验证 skills.sh discoverability
npm run publish:skills.sh -- --repo-url https://github.com/agent-dance/harness-engineering

# 预演 ClawHub 发布（不真的上传）
npm run publish:clawhub -- --dry-run

# 实际发布到全部 hub
CLAWHUB_TOKEN=clh_xxx npm run publish:hubs -- --repo-url https://github.com/agent-dance/harness-engineering
```

## GitHub Actions

推送到 `main` 后会自动：

1. 用 `npx skills add ... --list` 验证仓库能被 `skills.sh` 识别。
2. 检测本次提交变更过的 skills。
3. 如果仓库配置了 `CLAWHUB_TOKEN` secret，就把变更过的 skills 自动发布到 ClawHub。

## 需要的仓库 Secret

- `CLAWHUB_TOKEN`：ClawHub API token，用于 CI 自动发布。
