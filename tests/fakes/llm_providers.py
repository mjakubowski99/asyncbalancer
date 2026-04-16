from asyncbalancer.models.client import ProviderRequest, ProviderResponse
from asyncbalancer.models.resource import ResourceUnitCost, ResourceUnitCosts
from asyncbalancer.providers.iprovider import IProvider


class ChatGptFakeProvider(IProvider):
    def __init__(self, name: str = "chatgpt-fake"):
        self.name = name

    async def request(self, request: ProviderRequest) -> ProviderResponse:
        prompt = request.payload.get("prompt", "")
        return ProviderResponse(
            success=True,
            data={
                "provider": "chatgpt",
                "text": f"ChatGPT fake response for: {prompt}",
            },
            latency=220,
            error=None,
        )

    async def estimate_cost(self, request: ProviderRequest) -> ResourceUnitCosts:
        prompt = request.payload.get("prompt", "")
        estimated_tokens = max(1, int(len(prompt) / 4) + 12)
        return ResourceUnitCosts(
            costs={
                "tpm": ResourceUnitCost(key="tpm", amount=estimated_tokens),
                "rpm": ResourceUnitCost(key="rpm", amount=1),
            }
        )

    async def get_costs(self, response: ProviderResponse) -> ResourceUnitCosts:
        # Fake "real" usage slightly above estimate.
        return ResourceUnitCosts(
            costs={
                "tpm": ResourceUnitCost(key="tpm", amount=90),
                "rpm": ResourceUnitCost(key="rpm", amount=1),
            }
        )


class GeminiFakeProvider(IProvider):
    def __init__(self, name: str = "gemini-fake"):
        self.name = name

    async def request(self, request: ProviderRequest) -> ProviderResponse:
        prompt = request.payload.get("prompt", "")
        return ProviderResponse(
            success=True,
            data={
                "provider": "gemini",
                "text": f"Gemini fake response for: {prompt}",
            },
            latency=140,
            error=None,
        )

    async def estimate_cost(self, request: ProviderRequest) -> ResourceUnitCosts:
        prompt = request.payload.get("prompt", "")
        estimated_tokens = max(1, int(len(prompt) / 4) + 8)
        return ResourceUnitCosts(
            costs={
                "tpm": ResourceUnitCost(key="tpm", amount=estimated_tokens),
                "rpm": ResourceUnitCost(key="rpm", amount=1),
            }
        )

    async def get_costs(self, response: ProviderResponse) -> ResourceUnitCosts:
        return ResourceUnitCosts(
            costs={
                "tpm": ResourceUnitCost(key="tpm", amount=70),
                "rpm": ResourceUnitCost(key="rpm", amount=1),
            }
        )


class ClaudeFakeProvider(IProvider):
    def __init__(self, name: str = "claude-fake"):
        self.name = name

    async def request(self, request: ProviderRequest) -> ProviderResponse:
        prompt = request.payload.get("prompt", "")
        return ProviderResponse(
            success=True,
            data={
                "provider": "claude",
                "text": f"Claude fake response for: {prompt}",
            },
            latency=300,
            error=None,
        )

    async def estimate_cost(self, request: ProviderRequest) -> ResourceUnitCosts:
        prompt = request.payload.get("prompt", "")
        estimated_tokens = max(1, int(len(prompt) / 4) + 15)
        return ResourceUnitCosts(
            costs={
                "tpm": ResourceUnitCost(key="tpm", amount=estimated_tokens),
                "rpm": ResourceUnitCost(key="rpm", amount=1),
            }
        )

    async def get_costs(self, response: ProviderResponse) -> ResourceUnitCosts:
        return ResourceUnitCosts(
            costs={
                "tpm": ResourceUnitCost(key="tpm", amount=110),
                "rpm": ResourceUnitCost(key="rpm", amount=1),
            }
        )
