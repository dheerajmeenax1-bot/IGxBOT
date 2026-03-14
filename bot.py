import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor

# Constants
INSTAGRAM_API_URL = 'https://api.instagram.com/'
TELEGRAM_API_URL = 'https://api.telegram.org/bot{}/sendMessage'

class InstagramClient:
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.session = aiohttp.ClientSession()

    async def send_message(self, recipient, message):
        payload = {'recipient': recipient, 'message': message}
        async with self.session.post(INSTAGRAM_API_URL + 'send', json=payload) as response:
            return await response.json()

    async def close(self):
        await self.session.close()

async def send_messages(client, messages):
    tasks = [client.send_message(m[0], m[1]) for m in messages]
    return await asyncio.gather(*tasks)

async def process_messages(messages):
    clients = [InstagramClient('user1', 'pass1'), InstagramClient('user2', 'pass2')]
    with ThreadPoolExecutor(max_workers=50) as executor:
        loop = asyncio.get_event_loop()
        results = await asyncio.wait([loop.run_in_executor(executor, send_messages, client, messages) for client in clients])
        for client in clients:
            await client.close()
    return results

async def main():
    messages = [('recipient1', 'Hello!'), ('recipient2', 'Hi there!')]
    await process_messages(messages)

if __name__ == '__main__':
    asyncio.run(main())
