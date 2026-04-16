from typing import Type
from asyncbalancer.config import get_config
from typing import Callable

from asyncbalancer.providers.iprovider import IProvider

class ProviderRegistry:
    _providers = {}

    @classmethod
    def register(cls, name: str, provider: Type[IProvider]) -> None:
        cls._providers[name] = provider

    @classmethod
    def get(cls, name: str) -> Type[IProvider]:
        if name not in cls._providers:
            raise ValueError(f"Repository {name} not found")
        return cls._providers[name]

    @classmethod 
    def create(cls, name: str) -> IProvider:
        config = get_config()
        provider_class = cls.get(name)
        
        provider_config = config.get(f"providers.{name}").copy()
        provider_config.pop("resources", None)

        return provider_class(**provider_config)

    @classmethod
    def clear(cls) -> dict:
        providers = cls._providers.copy()

        cls._providers = {}

        return providers