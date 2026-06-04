"""测试全局钩子:在业务模块 import 之前注入必填 secrets,避免 pydantic ValidationError。

app.core.config.Settings 里 postgres_password / s3_* / llm_api_key 都是 SecretStr 必填,
没有默认值。如果不在 conftest 阶段 setdefault,后续 from app.core import ... 会直接报错。

同时显式覆盖 LLM_PROVIDER,避免用户 shell 里残留的 LLM_PROVIDER=xiaomi 之类的脏值污染测试。
"""

import os

# 必填 secrets:用 setdefault,允许 CI 环境用真值覆盖
os.environ.setdefault("POSTGRES_PASSWORD", "test-pg-password")
os.environ.setdefault("S3_ACCESS_KEY", "test-s3-key")
os.environ.setdefault("S3_SECRET_KEY", "test-s3-secret")
os.environ.setdefault("LLM_API_KEY", "test-llm-key")

# Literal 字段:必须显式赋值,不能 setdefault(否则用户 shell 的脏值会破坏 Literal 校验)
os.environ["LLM_PROVIDER"] = "mock"
