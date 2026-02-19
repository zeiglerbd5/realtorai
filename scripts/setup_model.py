#!/usr/bin/env python3
"""
RealtorAI Model Setup Script

Downloads and configures the MLX-optimized Llama 3.2 model for local inference.
"""

import argparse
import subprocess
import sys
from pathlib import Path


# Model configuration
# Note: Llama 3.2 only has 1B and 3B text models. For 8B, we use Llama 3.1.
DEFAULT_MODEL = "mlx-community/Llama-3.2-3B-Instruct-4bit"
ALTERNATIVE_MODELS = {
    "1b": "mlx-community/Llama-3.2-1B-Instruct-4bit",
    "3b": "mlx-community/Llama-3.2-3B-Instruct-4bit",
    "8b": "mlx-community/Llama-3.1-8B-Instruct-4bit",
}


def check_system_requirements():
    """Verify system meets requirements for MLX inference."""
    import platform

    print("Checking system requirements...")

    # Check macOS
    if platform.system() != "Darwin":
        print("Warning: MLX is optimized for macOS. Other platforms may have limited support.")
        return False

    # Check Apple Silicon
    machine = platform.machine()
    if machine not in ("arm64", "arm64e"):
        print("Warning: MLX requires Apple Silicon (M1/M2/M3). Intel Macs are not supported.")
        return False

    # Check memory (recommend 16GB+)
    try:
        import psutil
        memory_gb = psutil.virtual_memory().total / (1024**3)
        if memory_gb < 16:
            print(f"Warning: {memory_gb:.1f}GB RAM detected. 16GB+ recommended for 8B model.")
            print("Consider using the 3B model instead: --model 3b")
        else:
            print(f"Memory: {memory_gb:.1f}GB")
    except ImportError:
        print("Note: Install psutil to check memory: pip install psutil")

    print("System check passed!")
    return True


def download_model(model_name: str, cache_dir: Path | None = None):
    """Download the model using huggingface_hub."""
    print(f"\nDownloading model: {model_name}")
    print("This may take several minutes depending on your connection...")

    try:
        from huggingface_hub import snapshot_download

        # Download to HF cache or specified directory
        path = snapshot_download(
            repo_id=model_name,
            cache_dir=str(cache_dir) if cache_dir else None,
            local_files_only=False,
        )
        print(f"Model downloaded to: {path}")
        return path

    except ImportError:
        print("Error: huggingface_hub not installed.")
        print("Install with: pip install huggingface_hub")
        sys.exit(1)
    except Exception as e:
        print(f"Error downloading model: {e}")
        sys.exit(1)


def verify_model(model_name: str):
    """Verify the model loads correctly."""
    print("\nVerifying model...")

    try:
        from mlx_lm import load

        print("Loading model (this may take a moment)...")
        model, tokenizer = load(model_name)

        # Quick test
        print("Running inference test...")
        from mlx_lm import generate

        response = generate(
            model,
            tokenizer,
            prompt="Hello, I am",
            max_tokens=10,
            verbose=False,
        )
        print(f"Test output: {response}")
        print("Model verification successful!")
        return True

    except ImportError:
        print("Error: mlx-lm not installed.")
        print("Install with: pip install mlx-lm")
        return False
    except Exception as e:
        print(f"Error verifying model: {e}")
        return False


def create_env_template(model_name: str):
    """Create or update .env file with model configuration."""
    env_path = Path(__file__).parent.parent / ".env"
    env_example = Path(__file__).parent.parent / ".env.example"

    if not env_path.exists() and env_example.exists():
        import shutil
        shutil.copy(env_example, env_path)
        print(f"Created .env from .env.example")

    # Update model name in .env if it exists
    if env_path.exists():
        content = env_path.read_text()
        if "MODEL_NAME=" in content:
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if line.startswith("MODEL_NAME="):
                    lines[i] = f"MODEL_NAME={model_name}"
                    break
            env_path.write_text("\n".join(lines))
            print(f"Updated MODEL_NAME in .env")


def main():
    parser = argparse.ArgumentParser(
        description="Setup MLX model for RealtorAI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Download default 3B model (Llama 3.2)
  %(prog)s --model 8b         # Download larger 8B model (Llama 3.1)
  %(prog)s --model 1b         # Download smallest 1B model
  %(prog)s --verify-only      # Just verify existing model
  %(prog)s --list-models      # Show available models
        """,
    )
    parser.add_argument(
        "--model",
        choices=list(ALTERNATIVE_MODELS.keys()),
        default="3b",
        help="Model size to download (default: 3b)",
    )
    parser.add_argument(
        "--model-name",
        help="Override with specific HuggingFace model name",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Custom cache directory for model files",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing model, don't download",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip model verification after download",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List available models and exit",
    )

    args = parser.parse_args()

    if args.list_models:
        print("Available models:")
        for key, name in ALTERNATIVE_MODELS.items():
            marker = " (default)" if key == "3b" else ""
            print(f"  {key}: {name}{marker}")
        return

    # Determine model name
    model_name = args.model_name or ALTERNATIVE_MODELS[args.model]

    print("=" * 60)
    print("RealtorAI Model Setup")
    print("=" * 60)

    # Check system
    check_system_requirements()

    # Download if not verify-only
    if not args.verify_only:
        download_model(model_name, args.cache_dir)
        create_env_template(model_name)

    # Verify model
    if not args.skip_verify:
        if verify_model(model_name):
            print("\n" + "=" * 60)
            print("Setup complete!")
            print(f"Model: {model_name}")
            print("\nNext steps:")
            print("  1. Configure your .env file with Microsoft Graph credentials")
            print("  2. Run: realtorai-web")
            print("  3. Open http://localhost:8421 in your browser")
            print("=" * 60)
        else:
            print("\nModel verification failed. Please check the errors above.")
            sys.exit(1)


if __name__ == "__main__":
    main()
