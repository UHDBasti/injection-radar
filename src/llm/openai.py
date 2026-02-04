"""
OpenAI GPT LLM Client.
"""

import time
from typing import Any, Optional

from openai import AsyncOpenAI

from .base import BaseLLMClient, LLMResult, get_token_price


class OpenAIClient(BaseLLMClient):
    """Client für OpenAI GPT API."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        max_tokens: int = 1000,
        temperature: float = 0.1,
    ):
        super().__init__(api_key, model, max_tokens, temperature)
        self.client = AsyncOpenAI(api_key=api_key)

    @property
    def provider_name(self) -> str:
        return "openai"

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: Optional[list[dict]] = None,
    ) -> LLMResult:
        """Generiert eine Antwort von GPT.

        Args:
            system_prompt: System-Prompt für das LLM.
            user_prompt: User-Prompt (enthält den zu analysierenden Content).
            tools: Optionale Tool-Definitionen für Tool-Use Tests.

        Returns:
            LLMResult mit der Antwort und Metadaten.
        """
        start_time = time.time()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Request-Parameter
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": messages,
        }

        # Tools hinzufügen wenn angegeben (OpenAI Format)
        if tools:
            params["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"],
                    },
                }
                for tool in tools
            ]

        # API-Aufruf
        response = await self.client.chat.completions.create(**params)

        response_time_ms = int((time.time() - start_time) * 1000)

        # Response parsen
        choice = response.choices[0]
        message = choice.message

        # Tool-Calls extrahieren
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": tc.function.arguments,  # JSON string bei OpenAI
                })

        # Finish Reason mapping
        finish_reason_map = {
            "stop": "end_turn",
            "length": "max_tokens",
            "tool_calls": "tool_use",
            "content_filter": "content_filter",
        }
        finish_reason = finish_reason_map.get(choice.finish_reason, choice.finish_reason)

        # Kosten berechnen
        cost = self.estimate_cost(
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
        )

        return LLMResult(
            text=message.content or "",
            finish_reason=finish_reason,
            tokens_input=response.usage.prompt_tokens,
            tokens_output=response.usage.completion_tokens,
            response_time_ms=response_time_ms,
            tool_calls=tool_calls,
            has_tool_calls=len(tool_calls) > 0,
            raw_response=response,
            cost_estimated=cost,
        )

    def estimate_cost(self, tokens_input: int, tokens_output: int) -> float:
        """Berechnet die geschätzten Kosten für einen Request.

        Args:
            tokens_input: Anzahl Input-Tokens.
            tokens_output: Anzahl Output-Tokens.

        Returns:
            Geschätzte Kosten in USD.
        """
        pricing = get_token_price(self.provider_name, self.model)
        input_cost = (tokens_input / 1_000_000) * pricing["input"]
        output_cost = (tokens_output / 1_000_000) * pricing["output"]
        return input_cost + output_cost
