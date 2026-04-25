import argparse
import asyncio
from datetime import datetime, UTC
from typing import Sequence

from asyncbalancer.config import configure
from asyncbalancer.models.client import ProviderResponse
from asyncbalancer.models.resource import ResourceUnitCost, ResourceUnitCosts
from asyncbalancer.repository.repository_registry import RepositoryRegistry
from asyncbalancer.score_calculator import ProviderScoreCalculator
from asyncbalancer.state_factory import StateFactory


async def reset_state(
    provider: str,
    dry_run: bool = False,
) -> int:
    """Reset persisted provider state to defaults from config."""
    state_factory = StateFactory()
    available_providers = set(state_factory.get_providers())

    if provider not in available_providers:
        print(
            f"Unknown provider: {provider}. Available providers: "
            + ", ".join(sorted(available_providers))
        )
        return 2

    if dry_run:
        print(f"Dry run. Provider that would be reset: {provider}")
        return 0

    repository = RepositoryRegistry.create()
    await repository.remove_state(provider)
    try:
        await repository.save_state(state_factory.create(provider))
    except ValueError as exc:
        print(str(exc))
        return 2

    print(f"Reset completed for provider: {provider}")
    return 0


def _format_timestamp(timestamp: int | float) -> str:
    if timestamp <= 0:
        return "-"
    return datetime.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _format_provider_state(state) -> str:
    lines = [
        f"Provider: {state.name}",
        f"Score: {state.score:.4f}",
        "Circuit breaker:",
        f"  state: {state.circuit_breaker.state.value}",
        f"  failures: {state.circuit_breaker.failures}/{state.circuit_breaker.failure_threshold}",
        f"  retry_after: {state.circuit_breaker.retry_after}s",
        f"  last_failure_time: {_format_timestamp(state.circuit_breaker.last_failure_time)}",
        "Resources:",
    ]

    if not state.resource_units:
        lines.append("  - no resources")
    else:
        for key, resource in sorted(state.resource_units.items()):
            expires_at = resource.created_at + resource.ttl
            lines.extend(
                [
                    f"  - {key}:",
                    f"      used={resource.used}, reserved={resource.reserved}, capacity={resource.capacity}",
                    f"      ttl={resource.ttl}s, created_at={_format_timestamp(resource.created_at)}",
                    f"      expires_at={_format_timestamp(expires_at)}",
                ]
            )

    return "\n".join(lines)


def _recalculate_state_score(state) -> None:
    calculator = ProviderScoreCalculator()
    costs = ResourceUnitCosts(
        costs={
            key: ResourceUnitCost(key=key, amount=resource.used)
            for key, resource in state.resource_units.items()
        }
    )
    synthetic_response = ProviderResponse(
        success=True,
        data={},
        latency=0,
        error=None,
    )
    state.score = calculator.calculate(synthetic_response, costs)


async def show_state(provider: str) -> int:
    state_factory = StateFactory()
    available_providers = set(state_factory.get_providers())
    if provider not in available_providers:
        print(
            f"Unknown provider: {provider}. Available providers: "
            + ", ".join(sorted(available_providers))
        )
        return 2

    repository = RepositoryRegistry.create()
    state = await repository.get_state(provider)
    if state is None:
        print(f"No persisted state for provider: {provider}")
        return 1

    print(_format_provider_state(state))
    return 0


async def set_resource_used(provider: str, resource: str, used: int) -> int:
    if used < 0:
        print("Value for 'used' must be >= 0.")
        return 2

    state_factory = StateFactory()
    available_providers = set(state_factory.get_providers())
    if provider not in available_providers:
        print(
            f"Unknown provider: {provider}. Available providers: "
            + ", ".join(sorted(available_providers))
        )
        return 2

    repository = RepositoryRegistry.create()

    acquired = await repository.lock(provider)
    while not acquired:
        await asyncio.sleep(0.1)
        acquired = await repository.lock(provider)

    try:
        state = await repository.get_state(provider)
        if state is None:
            print(f"No persisted state for provider: {provider}")
            return 1

        if resource not in state.resource_units:
            print(
                f"Resource '{resource}' not found for provider '{provider}'. "
                + "Available resources: "
                + ", ".join(sorted(state.resource_units.keys()))
            )
            return 2

        state.resource_units[resource].used = used
        _recalculate_state_score(state)
        await repository.save_state(state)
    finally:
        await repository.unlock(provider)

    print(
        f"Updated provider '{provider}' resource '{resource}' used={used}."
    )
    return 0


async def set_resource_ttl(provider: str, resource: str, ttl: int) -> int:
    if ttl < 0:
        print("Value for 'ttl' must be >= 0.")
        return 2

    state_factory = StateFactory()
    available_providers = set(state_factory.get_providers())
    if provider not in available_providers:
        print(
            f"Unknown provider: {provider}. Available providers: "
            + ", ".join(sorted(available_providers))
        )
        return 2

    repository = RepositoryRegistry.create()

    acquired = await repository.lock(provider)
    while not acquired:
        await asyncio.sleep(0.1)
        acquired = await repository.lock(provider)

    try:
        state = await repository.get_state(provider)
        if state is None:
            print(f"No persisted state for provider: {provider}")
            return 1

        if resource not in state.resource_units:
            print(
                f"Resource '{resource}' not found for provider '{provider}'. "
                + "Available resources: "
                + ", ".join(sorted(state.resource_units.keys()))
            )
            return 2

        state.resource_units[resource].ttl = ttl
        state.resource_units[resource].created_at = datetime.now(UTC).timestamp()
        _recalculate_state_score(state)
        await repository.save_state(state)
    finally:
        await repository.unlock(provider)

    print(
        f"Updated provider '{provider}' resource '{resource}' ttl={ttl}s."
    )
    return 0


async def set_score(provider: str, score: float) -> int:
    if score < 0 or score > 100:
        print("Value for 'score' must be in range 0..100.")
        return 2

    state_factory = StateFactory()
    available_providers = set(state_factory.get_providers())
    if provider not in available_providers:
        print(
            f"Unknown provider: {provider}. Available providers: "
            + ", ".join(sorted(available_providers))
        )
        return 2

    repository = RepositoryRegistry.create()

    acquired = await repository.lock(provider)
    while not acquired:
        await asyncio.sleep(0.1)
        acquired = await repository.lock(provider)

    try:
        state = await repository.get_state(provider)
        if state is None:
            print(f"No persisted state for provider: {provider}")
            return 1

        state.score = score
        await repository.save_state(state)
    finally:
        await repository.unlock(provider)

    print(f"Updated provider '{provider}' score={score:.4f}.")
    return 0


async def adjust_resource_used(provider: str, resource: str, delta: int) -> int:
    state_factory = StateFactory()
    available_providers = set(state_factory.get_providers())
    if provider not in available_providers:
        print(
            f"Unknown provider: {provider}. Available providers: "
            + ", ".join(sorted(available_providers))
        )
        return 2

    repository = RepositoryRegistry.create()

    acquired = await repository.lock(provider)
    while not acquired:
        await asyncio.sleep(0.1)
        acquired = await repository.lock(provider)

    try:
        state = await repository.get_state(provider)
        if state is None:
            print(f"No persisted state for provider: {provider}")
            return 1

        if resource not in state.resource_units:
            print(
                f"Resource '{resource}' not found for provider '{provider}'. "
                + "Available resources: "
                + ", ".join(sorted(state.resource_units.keys()))
            )
            return 2

        current_used = state.resource_units[resource].used
        new_used = current_used + delta
        if new_used < 0:
            print(
                f"Cannot apply delta={delta}. Current used={current_used}, "
                "result would be negative."
            )
            return 2

        state.resource_units[resource].used = new_used
        _recalculate_state_score(state)
        await repository.save_state(state)
    finally:
        await repository.unlock(provider)

    print(
        f"Adjusted provider '{provider}' resource '{resource}' "
        f"used: {current_used} -> {new_used} (delta={delta})."
    )
    return 0


async def sync_config(provider: str | None = None) -> int:
    state_factory = StateFactory()
    available_providers = set(state_factory.get_providers())

    if provider is not None and provider not in available_providers:
        print(
            f"Unknown provider: {provider}. Available providers: "
            + ", ".join(sorted(available_providers))
        )
        return 2

    target_providers = [provider] if provider is not None else sorted(available_providers)
    if not target_providers:
        print("No providers found in config.")
        return 1

    repository = RepositoryRegistry.create()
    synced_states: list[str] = []
    had_errors = False

    for provider_name in target_providers:
        acquired = await repository.lock(provider_name)
        while not acquired:
            await asyncio.sleep(0.1)
            acquired = await repository.lock(provider_name)

        try:
            try:
                template_state = state_factory.create(provider_name)
            except ValueError as exc:
                print(str(exc))
                had_errors = True
                continue

            current_state = await repository.get_state(provider_name)
            if current_state is None:
                _recalculate_state_score(template_state)
                await repository.save_state(template_state)
                persisted_state = await repository.get_state(provider_name)
                synced_states.append(_format_provider_state(persisted_state))
                continue

            for resource_key, template_resource in template_state.resource_units.items():
                if resource_key in current_state.resource_units:
                    existing_resource = current_state.resource_units[resource_key]
                    should_reset_created_at = (
                        existing_resource.ttl != template_resource.ttl
                        or existing_resource.period != template_resource.period
                        or existing_resource.timezone != template_resource.timezone
                    )
                    existing_resource.capacity = template_resource.capacity
                    existing_resource.ttl = template_resource.ttl
                    existing_resource.period = template_resource.period
                    existing_resource.timezone = template_resource.timezone
                    if should_reset_created_at:
                        existing_resource.created_at = datetime.now(UTC).timestamp()
                else:
                    current_state.resource_units[resource_key] = template_resource

            _recalculate_state_score(current_state)
            await repository.save_state(current_state)
            persisted_state = await repository.get_state(provider_name)
            synced_states.append(_format_provider_state(persisted_state))
        finally:
            await repository.unlock(provider_name)

    if synced_states:
        print("\n\n".join(synced_states))

    if had_errors:
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asyncbalancer", description="Asyncbalancer CLI")
    parser.add_argument(
        "--config-file",
        help="Path to config file (config.toml or pyproject.toml).",
    )
    parser.add_argument(
        "--env-file",
        help="Path to .env file.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    reset_cmd = subparsers.add_parser(
        "reset-state",
        help="Reset persisted state for one provider.",
    )
    reset_cmd.add_argument(
        "provider",
        help="Provider name to reset.",
    )
    reset_cmd.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be reset without writing changes.",
    )
    show_cmd = subparsers.add_parser(
        "show-state",
        help="Show current persisted state for one provider.",
    )
    show_cmd.add_argument(
        "provider",
        help="Provider name to show.",
    )
    set_used_cmd = subparsers.add_parser(
        "set-resource-used",
        help="Update resource used value for one provider.",
    )
    set_used_cmd.add_argument(
        "provider",
        help="Provider name.",
    )
    set_used_cmd.add_argument(
        "resource",
        help="Resource name, e.g. tpm.",
    )
    set_used_cmd.add_argument(
        "used",
        type=int,
        help="New value for resource used.",
    )
    set_ttl_cmd = subparsers.add_parser(
        "set-resource-ttl",
        help="Update resource ttl value for one provider.",
    )
    set_ttl_cmd.add_argument(
        "provider",
        help="Provider name.",
    )
    set_ttl_cmd.add_argument(
        "resource",
        help="Resource name, e.g. tpm.",
    )
    set_ttl_cmd.add_argument(
        "ttl",
        type=int,
        help="New ttl value in seconds.",
    )
    set_score_cmd = subparsers.add_parser(
        "set-score",
        help="Update score value for one provider.",
    )
    set_score_cmd.add_argument(
        "provider",
        help="Provider name.",
    )
    set_score_cmd.add_argument(
        "score",
        type=float,
        help="New score in range 0..100.",
    )
    adjust_used_cmd = subparsers.add_parser(
        "adjust-resource-used",
        help="Increment/decrement resource used value for one provider.",
    )
    adjust_used_cmd.add_argument(
        "provider",
        help="Provider name.",
    )
    adjust_used_cmd.add_argument(
        "resource",
        help="Resource name, e.g. tpm.",
    )
    adjust_used_cmd.add_argument(
        "delta",
        type=int,
        help="Delta for used value (positive to increment, negative to decrement).",
    )
    sync_cmd = subparsers.add_parser(
        "sync-config",
        help="Sync provider limits from config and print updated state.",
    )
    sync_cmd.add_argument(
        "--provider",
        help="Sync only one provider. If omitted, sync all providers from config.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    configure(config_file=args.config_file, env_file=args.env_file)

    if args.command == "reset-state":
        return asyncio.run(
            reset_state(
                provider=args.provider,
                dry_run=args.dry_run,
            )
        )
    if args.command == "show-state":
        return asyncio.run(show_state(provider=args.provider))
    if args.command == "set-resource-used":
        return asyncio.run(
            set_resource_used(
                provider=args.provider,
                resource=args.resource,
                used=args.used,
            )
        )
    if args.command == "set-resource-ttl":
        return asyncio.run(
            set_resource_ttl(
                provider=args.provider,
                resource=args.resource,
                ttl=args.ttl,
            )
        )
    if args.command == "set-score":
        return asyncio.run(
            set_score(
                provider=args.provider,
                score=args.score,
            )
        )
    if args.command == "adjust-resource-used":
        return asyncio.run(
            adjust_resource_used(
                provider=args.provider,
                resource=args.resource,
                delta=args.delta,
            )
        )
    if args.command == "sync-config":
        return asyncio.run(sync_config(provider=args.provider))

    parser.error(f"Unknown command: {args.command}")
    return 2