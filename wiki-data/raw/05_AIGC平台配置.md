# AIGC平台配置

```toml
[project]
name = "星辰智创AIGC平台"
version = "3.2.1"
description = "企业级大模型训练与推理平台"
status = "production"

[deployment]
kubernetes_version = "1.28"
node_count = 48
gpu_nodes = 24
gpu_type = "NVIDIA A100 80G"
storage = "CephFS + MinIO"

[database]
vector_db = "Milvus 2.5"
relation_db = "PostgreSQL 16"
cache = "Redis 7.2"

[model]
base_model = "Qwen2.5-72B"
fine_tuned = true
context_window = 131072
embedding_model = "BAAI/bge-large-zh-v1.5"

[monitoring]
logging = "Loki + Grafana"
metrics = "Prometheus"
alerting = "AlertManager"
tracing = "Jaeger"
```
