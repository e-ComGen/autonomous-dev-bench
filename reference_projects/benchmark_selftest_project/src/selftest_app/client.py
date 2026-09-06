from .providers import build_provider


class Client:
    def __init__(self, provider: str = "upper") -> None:
        self._provider = build_provider(provider)

    def send(self, value: str) -> str:
        return self._provider.send(value)
