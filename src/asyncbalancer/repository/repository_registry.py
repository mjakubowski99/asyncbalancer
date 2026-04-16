from asyncbalancer.repository.istate_repository import IStateRepository
from typing import Type
from asyncbalancer.config import get_config
from inspect import signature, Parameter


class RepositoryRegistry:
    _repositories = {}

    @classmethod
    def register(cls, name: str, repository: Type[IStateRepository]) -> None:
        cls._repositories[name] = repository

    @classmethod
    def get(cls, name: str) -> Type[IStateRepository]:
        if name not in cls._repositories:
            raise ValueError(f"Repository {name} not found")
        return cls._repositories[name]

    @classmethod 
    def create(cls, name: str|None = None) -> IStateRepository:
        name = name or get_config().get('driver')

        config = get_config()
        repo_class = cls.get(name)

        driver_config = config.get(f"drivers.{name}") or {}

        ctor_signature = signature(repo_class.__init__)
        accepts_kwargs = any(
            parameter.kind == Parameter.VAR_KEYWORD
            for parameter in ctor_signature.parameters.values()
        )

        if accepts_kwargs:
            filtered_driver_config = driver_config
        else:
            allowed_params = {
                param_name
                for param_name, parameter in ctor_signature.parameters.items()
                if param_name != "self"
                and parameter.kind in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY)
            }
            filtered_driver_config = {
                key: value
                for key, value in driver_config.items()
                if key in allowed_params
            }

        return repo_class(**filtered_driver_config)
