import requests


class OllamaLLM:
    def __init__(
        self,
        model_name: str = "llama3.1:8b",
        base_url: str = "http://127.0.0.1:11434",
        temperature: float = 0.2,
    ):
        self.model_name = model_name
        self.base_url = base_url
        self.temperature = temperature

    def generate(self, messages):
        prompt = ""

        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            if role == "system":
                prompt += f"System: {content}\n"
            elif role == "user":
                prompt += f"User: {content}\n"
            elif role == "assistant":
                prompt += f"Assistant: {content}\n"

        prompt += "Assistant:"

        response = requests.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model_name,
                "prompt": prompt,
                "temperature": self.temperature,
                "stream": False,
            },
        )

        response.raise_for_status()
        return response.json()["response"].strip()