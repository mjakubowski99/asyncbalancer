import asyncio
import time
from asyncbalancer.models.resource import ResourceUnitCost
from google import genai
from asyncbalancer import ApiRouter
from asyncbalancer import ProviderRequest, ProviderResponse, ResourceUnitCosts
from asyncbalancer.providers.iprovider import IProvider
from asyncbalancer.providers.provider_registry import ProviderRegistry

class GeminiProvider(IProvider):
    def __init__(self, key: str, name: str):
        self.client = genai.Client(api_key=key)
        self.model_name = name

    async def request(self, request: ProviderRequest) -> ProviderResponse:
        start_time = time.perf_counter()

        prompt = request.payload.get('prompt', '')
        
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            
            latency = int((time.perf_counter() - start_time) * 1000)

            return ProviderResponse(
                success=True,
                data={
                    "text": response.text,
                    "usage": {
                        "prompt_tokens": response.usage_metadata.prompt_token_count,
                        "completion_tokens": response.usage_metadata.candidates_token_count,
                        "total_tokens": response.usage_metadata.total_token_count
                    }
                },
                latency=latency,
                error=None
            )
        except Exception as e:
            latency = int((time.perf_counter() - start_time) * 1000)
            return ProviderResponse(
                success=False,
                data={},
                latency=latency,
                error=str(e)
            )

    async def estimate_cost(self, request: ProviderRequest) -> ResourceUnitCosts:
        prompt = request.payload.get('prompt', '')
        
        if not prompt:
            return ResourceUnitCosts(costs={
                'tpm': ResourceUnitCost(key='tpm', amount=0)
            })

        char_count = len(prompt)
        
        estimated_tokens = int(char_count / 3.5) + 1
        
        estimated_tokens += 10

        return ResourceUnitCosts(
            costs={'tpm': ResourceUnitCost(key='tpm', amount=estimated_tokens)}
        )

    async def get_costs(self, response: ProviderResponse) -> ResourceUnitCosts:
        usage = response.data.get("usage", {})
        total_tokens = usage.get("total_tokens", 0)
        
        return ResourceUnitCosts(
            costs={
                'tpm': ResourceUnitCost(key='tpm', amount=total_tokens)
            }
        )

ProviderRegistry.register('gemini', GeminiProvider)
ProviderRegistry.register('gemma', GeminiProvider)

router = ApiRouter()

async def main():
    response = await router.request(ProviderRequest(payload={'prompt': 'Hello, world!'}))
    print(response)

asyncio.run(main())