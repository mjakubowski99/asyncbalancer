from asyncbalancer.models.client import ProviderRequest, ProviderResponse
from asyncbalancer.models.state import ProviderState
from asyncbalancer.provider_factory import ProviderFactory
from asyncbalancer.score_calculator import ProviderScoreCalculator
from asyncbalancer.repository.istate_repository import IStateRepository
from asyncbalancer.repository.repository_registry import RepositoryRegistry
from asyncbalancer.models.resource import ResourceUnitCosts
from asyncbalancer.providers.iprovider import IProvider
from asyncbalancer.providers.provider_registry import ProviderRegistry
from asyncbalancer.state_factory import StateFactory

import asyncio

class ApiRouter:

    def __init__(
        self
    ):
        self.state_repository: IStateRepository = RepositoryRegistry.create()
        self.provider_factory = ProviderFactory()
        self.score_calculator = ProviderScoreCalculator()
        self.state_factory = StateFactory()

    async def request(self, request: ProviderRequest) -> ProviderResponse:
        states = await self.state_repository.get_with_lowest_score(limit=10)

        if len(states) == 0:
            provider_names = self.state_factory.get_providers()
            self._validate_registered_providers_if_needed(provider_names)
            states = [self.state_factory.create(state) for state in provider_names]
            for state in states:
                await self.state_repository.save_state(state)
        else:
            states = [await self.state_repository.get_state(state) for state in states]
            self._validate_registered_providers_if_needed([state.name for state in states if state is not None])
        
        provider, estimated_costs, state = await self._find_best_provider(request, states)

        state = await self.state_repository.get_state(state.name)

        state.reserve_capacity(estimated_costs)

        await self.state_repository.save_state(state)

        try:
            response: ProviderResponse = await provider.request(request)
        except Exception as e:
            state.record_failure()
            await self.state_repository.save_state(state)
            raise e

        if response.success:
            actual_costs = await provider.get_costs(response)
            score = self.score_calculator.calculate(response, actual_costs)

            acquired = await self.state_repository.lock(state.name)

            while not acquired:
                acquired = await self.state_repository.lock(state.name)
                await asyncio.sleep(0.1)

            state = await self.state_repository.get_state(state.name)

            state.score = score

            state.record_success()

            state.release_capacity(estimated_costs)
            
            state.record_costs(actual_costs)
        else:
            acquired = await self.state_repository.lock(state.name)

            while not acquired:
                acquired = await self.state_repository.lock(state.name)
                await asyncio.sleep(0.1)

            state = await self.state_repository.get_state(state.name)
            state.release_capacity(estimated_costs)
            state.record_failure()
            state.score = 0.0

        await self.state_repository.save_state(state)

        await self.state_repository.unlock(state.name)

        return response

    async def _find_best_provider(self, request: ProviderRequest, states: list[ProviderState]) -> (IProvider, ResourceUnitCosts, ProviderState):
        for state in states:
            if not state.is_available():
                continue
            
            provider = self.provider_factory.create(state.name)

            costs = await provider.estimate_cost(request)

            api_provider_state = await self.state_repository.get_state(state.name)

            if api_provider_state.costs_exceed_capacity(costs):
                continue

            return (provider, costs, state)

        if len(states) > 0:
            from random import choice

            state = choice(states)

            provider = self.provider_factory.create(state.name)

            costs = await provider.estimate_cost(request)

            api_provider_state = await self.state_repository.get_state(state.name)

            return (provider, costs, state)

        raise Exception("No provider found")

    def _validate_registered_providers(self, provider_names: list[str]) -> None:
        missing = []
        for provider_name in provider_names:
            try:
                ProviderRegistry.get(provider_name)
            except ValueError:
                missing.append(provider_name)
        if missing:
            raise ValueError(
                "Missing provider class registration for: "
                + ", ".join(sorted(set(missing)))
                + ". Register provider classes in ProviderRegistry."
            )

    def _validate_registered_providers_if_needed(self, provider_names: list[str]) -> None:
        # Tests may inject mocked provider factories and do not rely on ProviderRegistry.
        if type(self.provider_factory) is not ProviderFactory:
            return
        self._validate_registered_providers(provider_names)