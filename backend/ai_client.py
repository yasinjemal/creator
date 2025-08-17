"""
Simple GPT-5 API client stub. Replace with real API integration and auth.
"""
import os
import requests

API_ENDPOINT = os.getenv("GPT5_API_ENDPOINT", "https://api.gpt5.example/v1/generate")
API_KEY = os.getenv("GPT5_API_KEY", "" )

class AIClient:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or API_KEY

    def generate(self, prompt: str, max_tokens: int = 256, **kwargs) -> str:
        # This is a stub. Replace with actual SDK or HTTP call to GPT-5.
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"prompt": prompt, "max_tokens": max_tokens}
        # For now, return a fake response for development.
        return f"[AI GENERATED] {prompt[:80]}..."


if __name__ == "__main__":
    c = AIClient()
    print(c.generate("Write a short Instagram caption in a friendly tone."))
