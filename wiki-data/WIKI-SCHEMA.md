# WIKI-SCHEMA.md — Wiki 页面格式规范

> 定义 Wiki 页面的结构规范，供 LLM 在生成页面时参考。
> LLM 应严格按照以下格式输出 Wiki 页面。

---

## 目录结构

```
wiki-data/
├── raw/                  # 原始文档（未处理）
├── wiki/                 # 生成的 Wiki 页面（.md）
├── index.md              # 页面索引（自动维护）
├── log.md                # 操作日志（自动维护）
├── backlinks.json        # 引用关系（自动维护）
├── tags.json             # 标签列表（自动维护）
└── WIKI-SCHEMA.md        # 本文件
```

## 页面格式

### Frontmatter（YAML）

每个页面必须有 frontmatter，格式：

```yaml
---
title: 页面标题
type: person | company | policy | project | concept | source-summary | auto-created
created: 2026-01-01
updated: 2026-01-01        # 可选
sources: [源文件名.md]
tags: [tag1, tag2]          # 优先使用已有 tags
valid_from: 2024-01-01      # 可选，制度类页面建议标注
valid_until: 2025-12-31     # 可选
---
```

### 正文结构

```
# 页面标题（H1）

## 概述（可选）

简要介绍。

## 内容章节（使用 H2）

具体内容...

## 参见

- [[相关页面1]]
- [[相关页面2]]
```

## 命名规则

- 文件名使用中文描述，不加日期前缀
- 文件名中避免空格，用下划线代替
- 关联页面用 `[[页面名]]` 交叉引用

## Tags 规范

常用 tags 分类：
- `employee` — 员工档案
- `hr` — 人力资源相关
- `finance` — 财务相关
- `policy` — 制度/政策
- `tech` — 技术相关
- `legal` — 法务/合规
- `company` — 公司信息
- `org` — 组织架构
- `active` — 当前有效
