---
title: 星辰智创AIGC平台
type: project
created: 2026-01-01
updated: 2026-01-01
sources: [05_AIGC平台配置.md]
tags: [tech, project, active]
---

# 星辰智创AIGC平台

## 概述

星辰智创AIGC平台是企业级大模型训练与推理平台，当前版本为 3.2.1，处于生产状态。平台基于 Kubernetes 集群部署，支持大规模模型训练与推理服务。

## 部署架构

- **Kubernetes 版本**：1.28
- **节点总数**：48 个
- **GPU 节点**：24 个（NVIDIA A100 80G）
- **存储系统**：CephFS + MinIO

## 数据库与缓存

- **向量数据库**：Milvus 2.5
- **关系数据库**：PostgreSQL 16
- **缓存系统**：Redis 7.2

## 模型能力

- **基础模型**：Qwen2.5-72B
- **微调状态**：已微调
- **上下文窗口**：131072 tokens
- **嵌入模型**：BAAI/bge-large-zh-v1.5

## 监控与可观测性

- **日志系统**：Loki + Grafana
- **指标系统**：Prometheus
- **告警系统**：AlertManager
- **链路追踪**：Jaeger

## 参见

- [[AI基础设施]]
- [[大模型2.0]]
- [[智能体平台]]
- [[AIGC平台]]
- [[星云容器平台]]