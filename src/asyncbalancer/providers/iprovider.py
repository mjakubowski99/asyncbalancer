from abc import ABC, abstractmethod

from asyncbalancer.models.client import ProviderRequest, ProviderResponse
from asyncbalancer.models.resource import ResourceUnitCosts

class IProvider(ABC):
    @abstractmethod
    async def request(self, request: ProviderRequest) -> ProviderResponse:
        pass

    @abstractmethod
    async def estimate_cost(self, request: ProviderRequest) -> ResourceUnitCosts:
        pass

    @abstractmethod
    async def get_costs(self, response: ProviderResponse) -> ResourceUnitCosts:
        pass