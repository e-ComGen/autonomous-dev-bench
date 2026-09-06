from typing import Protocol


class Provider(Protocol):
    def send(self, value: str) -> str: ...


class UpperProvider:
    def send(self, value: str) -> str:
        return value.upper()


class LowerProvider:
    def send(self, value: str) -> str:
        return value.lower()


def build_provider(name: str) -> Provider:
    # BENCHMARK_MUTATION:PROVIDER_DISPATCH_START
    if name == "upper":
        return UpperProvider()
    if name == "lower":
        return LowerProvider()
    raise ValueError(f"unknown provider: {name}")
    # BENCHMARK_MUTATION:PROVIDER_DISPATCH_END
