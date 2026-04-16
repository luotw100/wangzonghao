"""
LLM Worker - 异步轮询任务，调用大模型生成回复，并按计划时间发送
"""
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

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
    """大模型 API 客户端（异步）"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def chat(self, messages: List[Dict[str, str]]) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {"model": self.model, "messages": messages}

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            # 尝试 /chat/completions
            try:
                r = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            except Exception as e:
                logger.debug(f"OpenAI /chat/completions failed: {e}")

            # 尝试 /v1/chat/completions（兼容本地模型）
            try:
                payload["stream"] = False
                r = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers=headers,
                    json=payload
                )
                r.raise_for_status()
                data = r.json()
                if "choices" in data:
                    return data["choices"][0]["message"]["content"]
                elif "response" in data:
                    return data["response"]
            except Exception as e:
                logger.debug(f"OpenAI /v1/chat/completions failed: {e}")

        raise Exception("Failed to call LLM API with OpenAI-compatible format")


def parse_llm_response(text: str) -> List[Dict]:
    """
    解析 LLM 输出的 JSON，提取 messages 列表。
    期望格式:
      {"inner_thoughts": "...", "messages": [{"delay_seconds": N, "content": "..."}]}
    如果解析失败，回退为单条立即发送。
    """
    try:
        # 去掉可能的 markdown 代码块标记
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # 去掉首行（可能是 ```json 或 ```），末行若是 ``` 也去掉
            start = 1
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            cleaned = "\n".join(lines[start:end])

        data = json.loads(cleaned)
        if "messages" in data and isinstance(data["messages"], list):
            result = []
            for m in data["messages"]:
                if isinstance(m, dict) and "content" in m:
                    result.append({
                        "delay_seconds": int(m.get("delay_seconds", 0)),
                        "content": str(m["content"])
                    })
            if result:
                return result
    except Exception as e:
        logger.warning(f"JSON parse failed, using raw text as fallback: {e}")

    # 回退：单条立即发送
    return [{"delay_seconds": 0, "content": text}]


class Worker:
    """异步 Worker：任务处理 + 计划回复发送"""

    def __init__(self, api_base: str, llm_client: LLMClient):
        self.api_base = api_base.rstrip("/")
        self.llm = llm_client
        self.client = httpx.AsyncClient(timeout=30)

    async def close(self):
        await self.client.aclose()

    # --- API 调用封装 ---

    async def get_pending_tasks(self) -> List[Dict]:
        r = await self.client.get(f"{self.api_base}/tasks?status=pending&limit=5")
        r.raise_for_status()
        return r.json()

    async def get_conversation_data(self, conversation_id: str) -> Dict:
        r = await self.client.get(
            f"{self.api_base}/conversations/{conversation_id}/messages"
        )
        r.raise_for_status()
        return r.json()

    async def update_task_status(self, task_id: int, status: str, error_message: Optional[str] = None):
        payload = {"status": status}
        if error_message:
            payload["error_message"] = error_message
        r = await self.client.put(f"{self.api_base}/tasks/{task_id}", json=payload)
        r.raise_for_status()

    async def create_planned_replies(self, replies: List[Dict]):
        r = await self.client.post(
            f"{self.api_base}/planned_replies",
            json={"replies": replies}
        )
        r.raise_for_status()
        return r.json()

    async def get_due_planned_replies(self) -> List[Dict]:
        r = await self.client.get(f"{self.api_base}/planned_replies/due")
        r.raise_for_status()
        return r.json()

    async def send_robot_message(self, conversation_id: str, content: str):
        r = await self.client.post(
            f"{self.api_base}/messages",
            json={
                "conversation_id": conversation_id,
                "role": "robot",
                "msg_type": "text",
                "content": content
            }
        )
        r.raise_for_status()

    async def delete_planned_reply(self, reply_id: int):
        r = await self.client.delete(f"{self.api_base}/planned_replies/{reply_id}")
        r.raise_for_status()

    # --- 核心逻辑 ---

    async def process_task(self, task: Dict) -> bool:
        task_id = task["id"]
        conversation_id = task["conversation_id"]

        logger.info(f"Processing task {task_id}, conversation: {conversation_id}")
        await self.update_task_status(task_id, "processing")

        try:
            # 获取会话历史（包含 robot system_prompt 和 user_profile）
            data = await self.get_conversation_data(conversation_id)
            messages = data["messages"]
            robot = data.get("robot") or {}
            conv = data.get("conversation") or {}

            if ECHO_MODE:
                user_msgs = [m for m in messages if m["role"] == "user"]
                last_user = user_msgs[-1]["content"] if user_msgs else ""
                reply_text = f"[复读] {last_user}"
                planned = [{
                    "conversation_id": conversation_id,
                    "content": reply_text,
                    "send_at": datetime.now(timezone.utc).isoformat()
                }]
            else:
                # 构建 LLM messages
                chat_messages = []

                # system prompt = robot.system_prompt + user_profile
                system_parts = []
                if robot.get("system_prompt"):
                    system_parts.append(robot["system_prompt"])
                if conv.get("user_profile"):
                    system_parts.append("\n\n【当前粉丝档案】\n" + conv["user_profile"])
                if system_parts:
                    chat_messages.append({
                        "role": "system",
                        "content": "".join(system_parts)
                    })

                # 历史消息（完整上下文）
                for msg in messages:
                    if msg["role"] == "user":
                        chat_messages.append({"role": "user", "content": msg["content"]})
                    elif msg["role"] == "robot":
                        chat_messages.append({"role": "assistant", "content": msg["content"]})

                logger.info(f"Sending {len(chat_messages)} messages to LLM")

                # 调用 LLM
                response_text = await self.llm.chat(chat_messages)
                logger.debug(f"LLM response: {response_text[:200]}")

                # 解析 JSON，计算 send_at（累计 delay_seconds）
                msg_list = parse_llm_response(response_text)
                now = datetime.now(timezone.utc)
                cumulative_delay = 0
                planned = []
                for m in msg_list:
                    cumulative_delay += m["delay_seconds"]
                    send_at = now + timedelta(seconds=cumulative_delay)
                    planned.append({
                        "conversation_id": conversation_id,
                        "content": m["content"],
                        "send_at": send_at.isoformat()
                    })

            await self.create_planned_replies(planned)
            await self.update_task_status(task_id, "done")
            logger.info(f"Task {task_id} done, scheduled {len(planned)} replies")
            return True

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            if task.get("retry_count", 0) >= MAX_RETRIES:
                await self.update_task_status(task_id, "failed", str(e))
                logger.error(f"Task {task_id} exhausted retries")
            else:
                await self.update_task_status(task_id, "pending", str(e))
            return False

    async def task_processor_loop(self):
        """轮询待处理任务，调用 LLM 并存储计划回复"""
        logger.info("Task processor loop started")
        while True:
            try:
                tasks = await self.get_pending_tasks()
                if tasks:
                    logger.info(f"Found {len(tasks)} pending tasks")
                    for task in tasks:
                        await self.process_task(task)
                else:
                    logger.debug("No pending tasks")
            except Exception as e:
                logger.error(f"Task processor error: {e}")
            await asyncio.sleep(POLL_INTERVAL)

    async def reply_sender_loop(self):
        """每秒检查到期的计划回复，发送后删除"""
        logger.info("Reply sender loop started")
        while True:
            try:
                due_replies = await self.get_due_planned_replies()
                for reply in due_replies:
                    try:
                        await self.send_robot_message(reply["conversation_id"], reply["content"])
                        await self.delete_planned_reply(reply["id"])
                        logger.info(
                            f"Sent planned reply {reply['id']} to conv {reply['conversation_id']}"
                        )
                    except Exception as e:
                        logger.error(f"Failed to send planned reply {reply['id']}: {e}")
            except Exception as e:
                logger.error(f"Reply sender error: {e}")
            await asyncio.sleep(1)

    async def run(self):
        logger.info(f"Worker started | API: {self.api_base} | LLM: {LLM_BASE_URL}/{LLM_MODEL}")
        await asyncio.gather(
            self.task_processor_loop(),
            self.reply_sender_loop()
        )


async def _main():
    llm_client = LLMClient(LLM_BASE_URL, LLM_API_KEY, LLM_MODEL)
    worker = Worker(API_BASE_URL, llm_client)
    try:
        await worker.run()
    except KeyboardInterrupt:
        logger.info("Worker stopped")
    finally:
        await worker.close()


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
