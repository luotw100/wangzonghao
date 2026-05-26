---
name: architecture-skill-maintenance
description: Laborster 架构 Skill 维护规则。用于发现当前代码与 .agents/skills/repository-architecture 描述不一致时，按代码事实同步更新架构文档。
---

# Architecture Skill Maintenance / 架构 Skill 维护规则

## 什么时候使用

当你在当前仓库中遇到以下情况时，必须使用本 Skill：

- 实际代码、配置、Docker、前端行为或协议与 `repository-architecture` Skill 描述不一致。
- 修改了 `services/`（api、user_web、admin_web）或 `bridge/` 中任意代码或配置，并影响架构文档已有描述。
- 新增、删除、重命名 API、DB 字段、协议字段、环境变量、CLI 参数、Compose service、前端 tab 或关键流程。
- 验证过程中发现 `repository-architecture` Skill 中存在过时、缺漏或错误事实。

## 基本原则

1. **代码事实优先。** 当代码和架构 Skill 冲突时，以当前工作区代码为准。
2. **只同步当前事实。** 不把规划、建议、TODO、推测写入 `repository-architecture`。
3. **最小更新。** 只改与事实不一致的文档段落，不重写无关章节。
4. **同步引用链。** 改某个事实时，检查 root Skill、shared 文档、对应服务文档是否都需要同步。
5. **先验证再写结论。** 对拿不准的行为，先读代码或运行检查，不凭记忆更新 Skill。
6. **变更后自检。** 更新后检查旧文件引用、断链、过时关键词和 Git diff。

## 维护流程

### 1. 定位不一致来源

先确认冲突来自哪里：

- 后端代码：API endpoint、schema、model、worker、runtime、client。
- 前端代码：API client、route、tab、component、state flow。
- 基础设施：Compose、Dockerfile、Nginx、Vite、环境变量、CLI。
- 仓库设计文档：只作为现有文件状态记录，不能覆盖当前代码事实。

### 2. 找到对应架构文档

优先按范围更新：

- 跨服务边界或端到端流程：`repository-architecture/docs/shared/*`。
- Chat：`repository-architecture/docs/chat/*`。
- Bridge：`repository-architecture/docs/bridge/*`。
- Studio：`repository-architecture/docs/studio/*`。
- 文档地图或核心不变量：`repository-architecture/SKILL.md`。

### 3. 按代码事实改文档

写法要求：

- 使用中文描述，专业词汇可保留英文。
- 用“当前”描述已存在行为。
- 避免“未来会”“建议”“应该改成”“计划”等规划式表达。
- 如果记录一个异常或不一致，只写“当前文件事实”，不要扩展解决方案。

### 4. 自检

每次维护后至少检查：

```text
find .agents/skills/repository-architecture -type f | sort
grep -R "known-caveats\|Future\|future\|TODO\|规划方向\|将来\|未来" -n .agents/skills/repository-architecture || true
git status --short
git diff -- .agents/skills/repository-architecture .agents/skills/architecture-skill-maintenance
```

如果 root Skill 中列出的文档路径变化，必须确认目标文件存在。

## 冲突处理规则

- 如果代码改动是用户明确要求的：同步更新架构 Skill。
- 如果发现代码疑似 bug：不要在架构 Skill 中写修复建议；只记录当前实际行为，另行向用户确认是否修代码。
- 如果发现仓库设计文档与当前代码不一致：在 `current-code-notes.md` 中说明“设计文档不是当前 runtime”，不要把设计文档当实现。
- 如果用户要求架构 Skill 做 1:1 镜像：不得加入路线图、重构计划或产品设想。

## 输出要求

完成维护后，向用户报告：

- 更新了哪些 Skill 文件。
- 对应的是哪些代码事实变化。
- 自检是否通过。
- 是否还有需要用户决定的未处理项。
