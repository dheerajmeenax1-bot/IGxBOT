import asyncio
import aiohttp
from cachetools import TTLCache

# Caching setup
cache = TTLCache(maxsize=100, ttl=300)  # Cache with a 5-minute TTL

tasync def fetch(url, session):
    if url in cache:
        return cache[url]
    
    async with session.get(url) as response:
        data = await response.json()
        cache[url] = data  # Cache the result
        return data

async def fetch_batch(urls):
    async with aiohttp.ClientSession() as session:
        tasks = [fetch(url, session) for url in urls]
        return await asyncio.gather(*tasks)

async def main():
    urls = ["http://api.example.com/data1", "http://api.example.com/data2"]
    results = await fetch_batch(urls)
    print(results)

if __name__ == "__main__":
    asyncio.run(main())