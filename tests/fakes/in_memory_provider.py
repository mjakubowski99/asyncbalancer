from asyncbalancer.providers.iprovider import IProvider
from asyncbalancer.models.client import ProviderRequest, ProviderResponse
from asyncbalancer.models.resource import ResourceUnitCosts
from asyncbalancer.models.resource import ResourceUnitCost

class SuccessfulInMemoryProvider(IProvider):
    def __init__(self, name: str):
        self.name = name

    async def request(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            success=True,
            data={},
            latency=10,
            error=None
        )

    async def estimate_cost(self, request: ProviderRequest) -> ResourceUnitCosts:
        return ResourceUnitCosts(costs={
            "tpm": ResourceUnitCost(key="tpm", amount=10),
            "rpm": ResourceUnitCost(key="rpm", amount=10),
        })

    async def get_costs(self, response: ProviderResponse) -> ResourceUnitCosts:
        return ResourceUnitCosts(costs={
            "tpm": ResourceUnitCost(key="tpm", amount=20),
            "rpm": ResourceUnitCost(key="rpm", amount=20),
        })

class UnsuccessfulInMemoryProvider(IProvider):
    def __init__(self, name: str):
        self.name = name

    async def request(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            success=False,
            data={},
            latency=10,
            error="Error"
        )

    async def estimate_cost(self, request: ProviderRequest) -> ResourceUnitCosts:
        return ResourceUnitCosts(costs={
            "tpm": ResourceUnitCost(key="tpm", amount=10),
            "rpm": ResourceUnitCost(key="rpm", amount=10),
        })

    async def get_costs(self, response: ProviderResponse) -> ResourceUnitCosts:
        return ResourceUnitCosts(costs={
            "tpm": ResourceUnitCost(key="tpm", amount=20),
            "rpm": ResourceUnitCost(key="rpm", amount=20),
        })