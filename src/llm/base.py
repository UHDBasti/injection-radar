"""
Abstrakte Basisklasse für LLM-Provider.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from ..core.models import LLMRequest, LLMResponse


@dataclass
class LLMResult:
    """Ergebnis eines LLM-Aufrufs."""
    text: str
    finish_reason: str
    tokens_input: int
    tokens_output: int
    response_time_ms: int
    tool_calls: list[dict]
    has_tool_calls: bool
    raw_response: Any  # Provider-spezifisches Response-Objekt
    cost_estimated: float = 0.0


class BaseLLMClient(ABC):
    """Abstrakte Basisklasse für alle LLM-Provider."""

    def __init__(
        self,
        api_key: str,
        model: str,
        max_tokens: int = 1000,
        temperature: float = 0.1,
    ):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name des Providers (z.B. 'anthropic', 'openai')."""
        pass

    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: Optional[list[dict]] = None,
    ) -> LLMResult:
        """Generiert eine Antwort vom LLM.

        Args:
            system_prompt: System-Prompt für das LLM.
            user_prompt: User-Prompt (enthält den zu analysierenden Content).
            tools: Optionale Tool-Definitionen (um Tool-Call-Verhalten zu testen).

        Returns:
            LLMResult mit der Antwort und Metadaten.
        """
        pass

    @abstractmethod
    def estimate_cost(self, tokens_input: int, tokens_output: int) -> float:
        """Schätzt die Kosten für einen Request.

        Args:
            tokens_input: Anzahl Input-Tokens.
            tokens_output: Anzahl Output-Tokens.

        Returns:
            Geschätzte Kosten in USD.
        """
        pass

    def create_request_record(
        self,
        scraped_content_id: int,
        system_prompt: str,
        user_prompt: str,
        role: str = "subsystem",
    ) -> LLMRequest:
        """Erstellt ein LLMRequest-Objekt für die Datenbank.

        Args:
            scraped_content_id: ID des zugehörigen ScrapedContent.
            system_prompt: Verwendeter System-Prompt.
            user_prompt: Verwendeter User-Prompt.
            role: Rolle des LLM ("subsystem" oder "analyzer").

        Returns:
            LLMRequest-Objekt.
        """
        return LLMRequest(
            scraped_content_id=scraped_content_id,
            provider=self.provider_name,
            model=self.model,
            role=role,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=self.temperature,
            requested_at=datetime.utcnow(),
        )

    def create_response_record(
        self,
        request_id: int,
        result: LLMResult,
    ) -> LLMResponse:
        """Erstellt ein LLMResponse-Objekt für die Datenbank.

        Args:
            request_id: ID des zugehörigen LLMRequest.
            result: LLMResult vom generate()-Aufruf.

        Returns:
            LLMResponse-Objekt.
        """
        return LLMResponse(
            request_id=request_id,
            raw_response=result.text,
            finish_reason=result.finish_reason,
            tool_calls=result.tool_calls,
            has_tool_calls=result.has_tool_calls,
        )


# Token-Pricing (USD per 1M tokens) - Stand: 2024
PRICING = {
    "anthropic": {
        "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
        "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
        "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
        "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    },
    "openai": {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    },
    "google": {
        "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
        "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    },
}


def get_token_price(provider: str, model: str) -> dict[str, float]:
    """Holt die Token-Preise für ein Modell.

    Args:
        provider: Name des Providers.
        model: Name des Modells.

    Returns:
        Dict mit 'input' und 'output' Preisen pro 1M Tokens.
    """
    provider_pricing = PRICING.get(provider, {})
    return provider_pricing.get(model, {"input": 0.0, "output": 0.0})
