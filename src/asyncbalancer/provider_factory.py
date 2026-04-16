from asyncbalancer.providers.iprovider import IProvider
from asyncbalancer.providers.provider_registry import ProviderRegistry

class ProviderFactory:
    def create(self, key: str) -> IProvider:
        return ProviderRegistry.create(key)