# asyncbalancer

> ⚠️ **Warning:** This package is currently **not stable** and may change without notice.  
> Use it at your own risk.

`asyncbalancer` is a lightweight package for routing requests across multiple providers while storing provider state in Redis.

Key features:
- provider selection based on availability and score,
- circuit breaker per provider,
- resource limits (`tpm`, `rpm`, etc.) with TTL,
- CLI for state inspection and manual state administration.

## Requirements

- Python `>= 3.12`
- Redis (local or remote)

## Installation

From the project root:

```bash
pip install -e .
```

After installation, the CLI command is available:

```bash
asyncbalancer --help
```

You can also run it directly as a module:

```bash
python3 -m asyncbalancer --help
```

## Configuration

Configuration is loaded from the `[tool.asyncbalancer]` section in `pyproject.toml` (or `config.toml`).

Minimal example:

```toml
[tool.asyncbalancer]
driver = "redis"
resources_file = "./examples/config.json"
tier_order = ["free", "pro", "enterprise"]

[tool.asyncbalancer.drivers.redis]
host = "localhost"
port = 6379
db = 0

[tool.asyncbalancer.providers.gemini]
api_key = "your-api-key"
name = "gemini-2.5-flash"
tiers = ["pro", "enterprise"]
```

### Tier-based provider access

You can control which providers are available for each user tier.

- `tier_order` defines the fallback order from lower to higher tier.
- each provider can define `tiers` to limit access.
- if a provider does not define `tiers`, it is treated as available for all tiers.

Example:

```toml
[tool.asyncbalancer]
tier_order = ["free", "pro", "enterprise"]

[tool.asyncbalancer.providers.gemma]
tiers = ["free", "pro", "enterprise"]

[tool.asyncbalancer.providers.gemini]
tiers = ["pro", "enterprise"]

[tool.asyncbalancer.providers.claude]
tiers = ["enterprise"]
```

How routing works:

1. Router reads user tier from `ProviderRequest.tier` (or `ProviderRequest.options["tier"]`).
2. It first tries providers assigned to that tier.
3. If no provider can handle the request, it falls back to lower tiers based on `tier_order`.

Examples with `tier_order = ["free", "pro", "enterprise"]`:

- user tier `enterprise` -> try `enterprise`, then `pro`, then `free`
- user tier `pro` -> try `pro`, then `free`
- user tier `free` -> try only `free`

If request tier is missing, tier filtering is skipped (all providers can be considered).

### Defining resources in an external file

`resources_file` can point to a JSON or TOML file.  
`ASYNCBALANCER_RESOURCES_FILE` is also supported.

JSON example (`examples/config.json`):

```json
{
  "providers": {
    "gemini": {
      "resources": [
        { "name": "tpm", "value": 10000, "initial_ttl": 3600, "next_ttl": 3600 },
        { "name": "rpm", "value": 500, "initial_ttl": 60, "next_ttl": 60 }
      ]
    }
  }
}
```

## Library usage

1. Register provider classes in `ProviderRegistry`.
2. Create an `ApiRouter`.
3. Call `router.request(...)`.

Example:

```python
import asyncio
from asyncbalancer import ApiRouter, ProviderRequest
from asyncbalancer.providers.provider_registry import ProviderRegistry
from asyncbalancer.providers.iprovider import IProvider
from asyncbalancer.models.client import ProviderResponse
from asyncbalancer.models.resource import ResourceUnitCosts, ResourceUnitCost


class MyProvider(IProvider):
    def __init__(self, api_key: str, name: str):
        self.api_key = api_key
        self.name = name

    async def request(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(success=True, data={"text": "ok"}, latency=120, error=None)

    async def estimate_cost(self, request: ProviderRequest) -> ResourceUnitCosts:
        return ResourceUnitCosts(costs={"tpm": ResourceUnitCost(key="tpm", amount=20)})

    async def get_costs(self, response: ProviderResponse) -> ResourceUnitCosts:
        return ResourceUnitCosts(costs={"tpm": ResourceUnitCost(key="tpm", amount=24)})


ProviderRegistry.register("gemini", MyProvider)


async def main():
    router = ApiRouter()
    response = await router.request(ProviderRequest(payload={"prompt": "Hello"}))
    print(response)


asyncio.run(main())
```

## CLI commands

Show all commands:

```bash
asyncbalancer --help
```

### `show-state`

Shows current state for a provider.

```bash
asyncbalancer show-state gemini
```

### `reset-state`

Resets provider state to values from config/resources.

```bash
asyncbalancer reset-state gemini
```

Dry-run mode:

```bash
asyncbalancer reset-state gemini --dry-run
```

### `set-resource-used`

Sets `used` for a resource and recalculates score.

```bash
asyncbalancer set-resource-used gemini tpm 1200
```

### `adjust-resource-used`

Increments/decrements `used` by `delta` and recalculates score.

```bash
asyncbalancer adjust-resource-used gemini tpm 150
asyncbalancer adjust-resource-used gemini tpm -80
```

### `set-resource-ttl`

Sets resource `ttl` (and updates `created_at` to now) and recalculates score.

```bash
asyncbalancer set-resource-ttl gemini tpm 3600
```

### `sync-config`

Synchronizes limits from config into Redis state:
- updates limits (`capacity`, `ttl`),
- keeps current usage (`used`, `reserved`) unchanged,
- recalculates score,
- prints state after update.

Single provider:

```bash
asyncbalancer sync-config --provider gemini
```

All providers:

```bash
asyncbalancer sync-config
```

## CLI exit codes

- `0` success
- `1` provider state not found / no providers found
- `2` argument or configuration validation error

## Locking note

State-mutating commands (`set-resource-used`, `adjust-resource-used`, `set-resource-ttl`, `sync-config`) wait for a provider lock before writing state to avoid clobbering concurrent updates.
