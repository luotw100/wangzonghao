---
name: deploy
description: 提交代码并部署到 N100 服务器。用于代码改完后需要验证或上线时。
---

# 部署流程

本项目的开发机是 macOS（本机），部署目标是家里的 N100 服务器（Ubuntu），通过 Docker Compose 运行。

## 环境信息

- **开发机**: macOS，代码目录 `/Users/luotengwei/code/wangzonghao`
- **部署机**: N100（~/.ssh/config 中已配置，密钥免密登录），Ubuntu 系统
- **部署机代码目录**: `/home/luotw/code/wangzonghao`
- **Git 仓库**: 私人 GitHub 仓库，直接在 master 分支上提交和推送

## 步骤

### 1. 在本机提交并推送

```bash
git add <changed-files>
git commit -m "描述"
git push origin master
```

### 2. 在 N100 上拉取代码

```bash
ssh N100 "cd /home/luotw/code/wangzonghao && git pull"
```

### 3. 在 N100 上重新构建并启动

```bash
ssh N100 "cd /home/luotw/code/wangzonghao && docker compose up -d --build"
```

### 4. 验证服务状态

```bash
ssh N100 "cd /home/luotw/code/wangzonghao && docker compose ps"
```

如果需要查看日志排查问题：

```bash
ssh N100 "cd /home/luotw/code/wangzonghao && docker compose logs --tail=50 <service-name>"
```

服务名包括：`nginx`、`chat`、`robot-api`、`robot-worker`。
