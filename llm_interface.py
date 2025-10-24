from transformers import pipeline
from abc import ABC, abstractmethod

class BaseLLM(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        pass

class HuggingFaceLLM(BaseLLM):
    def __init__(self, model_name: str = "google/flan-t5-large"):
        self.generator = pipeline("text2text-generation", model=model_name)

    def generate(self, prompt: str) -> str:
        # result = self.generator(prompt, max_new_tokens=200)
        result = self.generator(prompt, max_new_tokens=200, do_sample=False)
        return result[0]["generated_text"]

def call_llm(system: str, user: str, temperature: float = 0.3, max_tokens: int = 900) -> str:
    # Reuse HF pipeline for now
    prompt = system + "\n\n" + user
    llm = HuggingFaceLLM()
    return llm.generate(prompt)

