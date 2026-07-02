from models.config import Settings
from utils.vertex import make_client
import asyncio

async def check_model(model_name: str, client):
    try:
        # We need to use the async client here
        response = await client.aio.models.generate_content(
            model=model_name,
            contents="test",
        )
        # The model is available if we get a response
        print(f"Model '{model_name}' is available.")
    except Exception as e:
        print(f"Model '{model_name}' is not available or an error occurred: {e}")

async def main():
    settings = Settings()
    client = make_client(settings)
    await check_model("gemini-pro", client)

if __name__ == "__main__":
    asyncio.run(main())
