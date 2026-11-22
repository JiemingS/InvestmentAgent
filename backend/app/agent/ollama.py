import json
from urllib.parse import urlsplit

import httpx

from .models import PublicSearchIdeas

MODEL = "gemma4:31b"
MAX_RESPONSE_BYTES = 128_000


class OllamaError(RuntimeError):
    pass


class Ollama:
    model = MODEL

    def __init__(self, url: str = "http://127.0.0.1:11434"):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "::1")
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
        ):
            raise ValueError("INVESTMENT_OLLAMA_URL must be a loopback HTTP origin.")
        self.url = url.rstrip("/") + "/api/chat"

    async def expand_public_search(self, clauses: list[str], instruments: list[str]) -> list[str]:
        message = await self.chat([
            {"role": "system", "content":
             "Propose two to four short English public web search queries for the supplied public topic. "
             "Translate and vary useful synonyms. For a request for headlines without a topic, use general current world news. "
             "Use the listed public instruments where relevant. Avoid dates, URLs, credentials and personal information. "
             "Return only the JSON schema."},
            {"role": "user", "content": json.dumps({"public_topic": clauses, "public_instruments": instruments}, ensure_ascii=False)},
        ], schema=PublicSearchIdeas.model_json_schema())
        return PublicSearchIdeas.model_validate_json(message.get("content", "")).queries

    async def chat(self, messages: list[dict], *, tools: list[dict] | None = None, schema: dict | None = None) -> dict:
        body = {
            "model": self.model, "stream": False, "think": False, "messages": messages,
            "options": {"temperature": 0, "num_ctx": 12288, "num_predict": 1200 if schema else 512},
        }
        if tools:
            body["tools"] = tools
        if schema:
            body["format"] = schema
        try:
            async with httpx.AsyncClient(timeout=35, trust_env=False, follow_redirects=False) as client:
                async with client.stream("POST", self.url, json=body) as response:
                    if response.status_code == 404:
                        raise OllamaError(f"The local Ollama model {self.model} is unavailable.")
                    response.raise_for_status()
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_RESPONSE_BYTES:
                            raise OllamaError("Ollama returned an oversized response.")
            message = json.loads(content)["message"]
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise ValueError("Invalid Ollama message")
            return message
        except httpx.TimeoutException as error:
            raise TimeoutError("Ollama did not respond within its time budget.") from error
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            raise OllamaError("The local Ollama service is unavailable or returned an invalid response.") from error
