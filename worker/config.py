# Worker 配置
# 请根据你的 LLM API 进行配置

import os

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

# 请求超时（秒）
REQUEST_TIMEOUT = 120

# Worker 轮询间隔（秒）
POLL_INTERVAL = 2

# 最大重试次数
MAX_RETRIES = 3

# 后端 API 地址
API_BASE_URL = "http://localhost:23456/api"

# 测试模式：True = 复读机模式，False = 调用真实 LLM
ECHO_MODE = False
