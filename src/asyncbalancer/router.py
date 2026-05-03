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
from contextlib import asynccontextmanager
from datetime import datetime, UTC
import time

import asyncio

class ApiRouter:

    def __init__(
        self
    ):
        self.state_repository: IStateRepository = RepositoryRegistry.create()
        self.provider_factory = ProviderFactory()
        self.score_calculator = ProviderScoreCalculator()
        self.state_factory = StateFactory()

    async def request(self, request: ProviderRequest, tries: int = 3, timeout_seconds: int = 120) -> ProviderResponse:
        start_time = time.time()
        last_response = None 
        last_exception = None

        for _ in range(tries):
            try:
                last_response = await self.__make_request(request)
            except Exception as e:
                last_exception = e
                await asyncio.sleep(0.1)
                continue

            end_time = time.time()

            if end_time - start_time > timeout_seconds:
                raise Exception("Api router timed out")

            if last_response.success:
                return last_response

            await asyncio.sleep(0.1)
            continue

        if last_exception:
            raise last_exception

        return last_response

    
    async def __make_request(self, request: ProviderRequest) -> ProviderResponse:
        ranked_provider_names = await self.state_repository.get_with_lowest_score(limit=50)
        create_missing_states = len(ranked_provider_names) == 0
        if create_missing_states:
            ranked_provider_names = self.state_factory.get_providers()

        provider, estimated_costs, state = await self._select_provider_with_tier_fallback(
            request=request,
            ranked_provider_names=ranked_provider_names,
            create_missing_states=create_missing_states,
        )

        async with self._locked_state(state.name) as state:
            state.reserve_capacity(estimated_costs)
            await self.state_repository.save_state(state)

        try:
            response: ProviderResponse = await provider.request(request)
        except Exception as e:
            async with self._locked_state(state.name) as state:
                state.release_capacity(estimated_costs)
                state.record_failure()
                await self.state_repository.save_state(state)
            raise e

        async with self._locked_state(state.name) as state:
            state = await self.state_repository.get_state(state.name)
            if response.success:
                actual_costs = await provider.get_costs(response)
                state.score = self.score_calculator.calculate(response, actual_costs, state.score)
                state.record_success()
                state.release_capacity(estimated_costs)
                state.record_costs(actual_costs)
            else:
                state.score = self.score_calculator.calculate(
                    response,
                    estimated_costs,
                    state.score,
                )
                state.release_capacity(estimated_costs)
                state.record_failure()
            await self.state_repository.save_state(state)

        return response

    @asynccontextmanager
    async def _locked_state(self, name: str, max_retries: int = 50, delay: float = 0.1):
        for attempt in range(max_retries):
            if await self.state_repository.lock(name):
                break
            await asyncio.sleep(delay)
        else:
            raise TimeoutError(f"Could not acquire lock for '{name}' after {max_retries} attempts")
        try:
            yield await self.state_repository.get_state(name)
        finally:
            await self.state_repository.unlock(name)

    async def _select_provider_with_tier_fallback(
        self,
        request: ProviderRequest,
        ranked_provider_names: list[str],
        create_missing_states: bool = False,
    ) -> tuple[IProvider, ResourceUnitCosts, ProviderState]:
        requested_tier = request.tier or request.options.get("tier")
        tier_chain = self.state_factory.get_tier_fallback_chain(requested_tier)

        for index, tier in enumerate(tier_chain):
            tier_provider_names = [
                provider_name
                for provider_name in ranked_provider_names
                if self.state_factory.provider_supports_tier(provider_name, tier)
            ]
            if not tier_provider_names:
                continue

            self._validate_registered_providers_if_needed(tier_provider_names)

            if create_missing_states:
                tier_states = [self.state_factory.create(provider_name) for provider_name in tier_provider_names]
                for state in tier_states:
                    await self.state_repository.save_state(state)
            else:
                tier_states = await self.state_repository.get_states(tier_provider_names)

            if not tier_states:
                continue

            allow_random_fallback = index == len(tier_chain) - 1
            selected = await self._find_best_provider(
                request,
                tier_states,
                allow_random_fallback=allow_random_fallback,
            )
            if selected is not None:
                return selected

        raise Exception("No provider found")

    async def _find_best_provider(
        self,
        request: ProviderRequest,
        states: list[ProviderState],
        allow_random_fallback: bool = True,
    ) -> tuple[IProvider, ResourceUnitCosts, ProviderState] | None:
        for state in states:
            if not state.is_available():
                continue
            
            provider = self.provider_factory.create(state.name)

            costs = await provider.estimate_cost(request)

            api_provider_state = await self.state_repository.get_state(state.name)

            if api_provider_state.costs_exceed_capacity(costs):
                continue

            return (provider, costs, state)

        if allow_random_fallback and len(states) > 0:
            from random import choice

            state = choice(states)

            provider = self.provider_factory.create(state.name)

            costs = await provider.estimate_cost(request)

            api_provider_state = await self.state_repository.get_state(state.name)

            return (provider, costs, state)

        return None

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