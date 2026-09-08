"""One explicit paid-run authorization. Credentials are not serialized with the task."""
import getpass
import os
import sys


def authorize(settings, episodes, allowed):
    if not allowed:
        if not sys.stdin.isatty():
            raise ValueError("Paid requests require --allow-live-model in noninteractive runs")
        print(f"Run {episodes} paid episodes? Each entire arm: {settings.requests_per_arm} requests, "
              f"{settings.output_tokens_per_request} output tokens/request, {settings.arm_seconds}s.")
        print("These are request/time caps, NOT a hard dollar limit.")
        if input("Type YES to run both arms: ").strip() != "YES":
            raise ValueError("MODEL_SPEND_NOT_AUTHORIZED")
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    # Explicit automation authorization never falls back to interactive key input.
    if not key and not allowed and sys.stdin.isatty():
        key = getpass.getpass("DeepSeek API key (not saved): ").strip()
    if not key:
        raise ValueError("DEEPSEEK_API_KEY_MISSING")
    return key
