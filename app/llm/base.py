from abc import ABC, abstractmethod

class LLMClient(ABC):

    @abstractmethod     # Indicate that this method must be implemented by subclasses
    def chat(self, user_message: str) -> str:
        """Send a message to the LLM and receive a response."""
        pass