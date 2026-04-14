"""
LLM Worker - 轮询待处理任务，调用大模型生成回复
"""
import time
import json
import logging
from typing import List, Dict, Any

import httpx

from config import (
    LLM_BASE_URL,
    LLM_API_KEY,
    LLM_MODEL,
    REQUEST_TIMEOUT,
    POLL_INTERVAL,
    MAX_RETRIES,
    API_BASE_URL,
    ECHO_MODE
)

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class LLMClient:
    """大模型 API 客户端"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.client = httpx.Client(timeout=REQUEST_TIMEOUT)

    def chat(self, messages: List[Dict[str, str]]) -> str:
        """
        调用大模型聊天接口

        Args:
            messages: [{"role": "user"/"assistant"/"system", "content": "..."}]

        Returns:
            模型生成的回复文本
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "messages": messages
        }

        # 兼容不同 API 格式
        # OpenAI 格式
        try:
            response = self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.debug(f"OpenAI format failed: {e}")

        # Claude 格式 (Claude API 使用不同的端点)
        try:
            anthropic_messages = self._to_anthropic_format(messages)
            payload = {
                "model": self.model,
                "messages": anthropic_messages,
                "max_tokens": 4096
            }
            response = self.client.post(
                f"{self.base_url}/v1/messages",
                headers={**headers, "x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]
        except Exception as e:
            logger.debug(f"Anthropic format failed: {e}")

        # 通用格式 (如 local AI)
        try:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False
            }
            response = self.client.post(
                f"{self.base_url}/v1/chat/completions",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            if "choices" in data:
                return data["choices"][0]["message"]["content"]
            elif "response" in data:
                return data["response"]
        except Exception as e:
            logger.debug(f"Generic format failed: {e}")

        raise Exception(f"Failed to call LLM API with any known format")

    def _to_anthropic_format(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """将消息转换为 Anthropic 格式"""
        result = []
        for msg in messages:
            if msg["role"] == "system":
                result.insert(0, {"role": "user", "content": msg["content"]})
            else:
                role = "assistant" if msg["role"] == "assistant" else msg["role"]
                result.append({"role": role, "content": msg["content"]})
        return result

    def close(self):
        self.client.close()


class Worker:
    """任务处理器"""

    def __init__(self, api_base: str, llm_client: LLMClient):
        self.api_base = api_base.rstrip("/")
        self.llm = llm_client
        self.client = httpx.Client(timeout=30)

    def get_pending_tasks(self) -> List[Dict]:
        """获取待处理任务"""
        response = self.client.get(f"{self.api_base}/tasks?status=pending&limit=5")
        response.raise_for_status()
        return response.json()

    def get_conversation_messages(self, conversation_id: str) -> Dict:
        """获取会话历史消息"""
        response = self.client.get(
            f"{self.api_base}/conversations/{conversation_id}/messages"
        )
        response.raise_for_status()
        return response.json()

    def send_robot_message(self, conversation_id: str, content: str) -> Dict:
        """发送机器人回复"""
        response = self.client.post(
            f"{self.api_base}/messages",
            json={
                "conversation_id": conversation_id,
                "role": "robot",
                "msg_type": "text",
                "content": content
            }
        )
        response.raise_for_status()
        return response.json()

    def update_task_status(self, task_id: int, status: str, error_message: str = None):
        """更新任务状态"""
        payload = {"status": status}
        if error_message:
            payload["error_message"] = error_message

        response = self.client.put(
            f"{self.api_base}/tasks/{task_id}",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    def process_task(self, task: Dict) -> bool:
        """
        处理单个任务

        Returns:
            True if processed successfully, False otherwise
        """
        task_id = task["id"]
        conversation_id = task["conversation_id"]

        logger.info(f"Processing task {task_id}, conversation: {conversation_id}")

        # 1. 标记为处理中
        self.update_task_status(task_id, "processing")

        try:
            # 2. 获取会话历史
            data = self.get_conversation_messages(conversation_id)
            messages = data["messages"]
            robot = data["robot"]

            # 3. 获取用户最后一条消息
            user_messages = [m for m in messages if m["role"] == "user"]
            last_user_message = user_messages[-1]["content"] if user_messages else ""

            # ECHO_MODE: 复读机模式，直接回复用户消息
            if ECHO_MODE:
                logger.info(f"[ECHO MODE] Task {task_id}: echoing '{last_user_message}'")
                reply = f"[复读] {last_user_message}"
            else:
                # 4. 构建消息列表
                chat_messages = []

                # 添加 system prompt
                if robot and robot.get("system_prompt"):
                    chat_messages.append({
                        "role": "system",
                        "content": robot["system_prompt"]
                    })

                # 添加历史消息
                for msg in messages:
                    if msg["role"] in ["user", "robot"]:
                        role = "user" if msg["role"] == "user" else "assistant"
                        chat_messages.append({
                            "role": role,
                            "content": msg["content"]
                        })

                logger.info(f"Sending {len(chat_messages)} messages to LLM")

                # 5. 调用 LLM
                reply = self.llm.chat(chat_messages)

            # 6. 发送回复
            self.send_robot_message(conversation_id, reply)

            # 7. 标记完成
            self.update_task_status(task_id, "done")
            logger.info(f"Task {task_id} completed")
            return True

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")

            # 检查重试次数
            if task.get("retry_count", 0) >= MAX_RETRIES:
                self.update_task_status(task_id, "failed", str(e))
                logger.error(f"Task {task_id} failed after max retries")
            else:
                # 重置为 pending 供下次重试
                self.update_task_status(task_id, "pending", str(e))

            return False

    def run(self):
        """主循环"""
        logger.info(f"Worker started, polling every {POLL_INTERVAL}s")
        logger.info(f"API base: {self.api_base}")
        logger.info(f"LLM: {LLM_BASE_URL}/{LLM_MODEL}")

        while True:
            try:
                tasks = self.get_pending_tasks()

                if tasks:
                    logger.info(f"Found {len(tasks)} pending tasks")
                    for task in tasks:
                        self.process_task(task)
                else:
                    logger.debug("No pending tasks")

            except Exception as e:
                logger.error(f"Error in main loop: {e}")

            time.sleep(POLL_INTERVAL)


def main():
    llm_client = LLMClient(LLM_BASE_URL, LLM_API_KEY, LLM_MODEL)
    worker = Worker(API_BASE_URL, llm_client)

    try:
        worker.run()
    except KeyboardInterrupt:
        logger.info("Worker stopped")
    finally:
        llm_client.close()


if __name__ == "__main__":
    main()
