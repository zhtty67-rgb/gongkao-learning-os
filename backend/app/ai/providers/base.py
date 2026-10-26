"""Protocol definition for underlying AI model providers."""
from typing import Protocol, runtime_checkable

from ..schemas import Message, ModelPolicyConfig


@runtime_checkable
class ModelProvider(Protocol):
    """Low-level provider interface.
    
    ModelGateway wraps this to handle policy routing and Pydantic validation.
    """

    provider_name: str

    async def generate(
        self,
        messages: list[Message],
        config: ModelPolicyConfig,
        json_mode: bool = False,
    ) -> tuple[str, dict[str, int]]:
        """Generate response text and return (content, token_usage)."""
        ...
