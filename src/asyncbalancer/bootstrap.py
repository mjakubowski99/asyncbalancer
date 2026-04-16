from .repository.repository_registry import RepositoryRegistry
from .repository.provider_state_redis_repository import ProviderStateRedisRepository

def register_default_repositories():
    RepositoryRegistry.register('redis', ProviderStateRedisRepository)