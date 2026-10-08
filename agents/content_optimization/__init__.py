"""Optional, fail-closed content improvements for the existing pipeline."""

def optimize_content(*args, **kwargs):
    # Keep offline analytics free of the Gemini SDK and .env loading.
    from .optimizer import optimize_content as run
    return run(*args, **kwargs)

__all__ = ["optimize_content"]
