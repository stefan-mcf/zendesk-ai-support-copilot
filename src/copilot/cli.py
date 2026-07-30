import argparse
import asyncio
import json
from pathlib import Path

from copilot.config import Settings
from copilot.evaluation import evaluate
from copilot.fixtures import dataset_sha256, load_dataset, support_cases
from copilot.model_provider import (
    BedrockDraftProvider,
    DeterministicDraftProvider,
    DraftProvider,
)
from copilot.retrieval import HybridRetriever
from copilot.service import CopilotService
from copilot.storage import MemoryStore


async def evaluate_dataset(
    dataset_path: Path,
    *,
    provider_name: str = "deterministic",
    aws_region: str | None = None,
    bedrock_model_id: str = "openai.gpt-oss-20b-1:0",
    max_output_tokens: int = 300,
) -> dict[str, object]:
    if not 64 <= max_output_tokens <= 300:
        raise ValueError("--max-output-tokens must be between 64 and 300")
    dataset = load_dataset(dataset_path)
    store = MemoryStore()
    await store.replace_seed(dataset.articles, support_cases(dataset))
    if provider_name == "bedrock":
        if not aws_region:
            raise ValueError("--aws-region is required with --provider bedrock")
        provider: DraftProvider = BedrockDraftProvider(
            region=aws_region,
            model_id=bedrock_model_id,
            max_output_tokens=max_output_tokens,
        )
    else:
        provider = DeterministicDraftProvider()
    service = CopilotService(
        Settings(environment="evaluation", dataset_path=dataset_path),
        store,
        HybridRetriever(dataset.articles),
        provider,
    )
    report = await evaluate(dataset, service)
    payload = report.model_dump(mode="json")
    payload["dataset_sha256"] = dataset_sha256(dataset_path)
    return payload


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Run the deterministic Support Copilot evaluation.")
    value.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/support-cases.json"),
    )
    value.add_argument("--output", type=Path)
    value.add_argument(
        "--provider",
        choices=["deterministic", "bedrock"],
        default="deterministic",
    )
    value.add_argument("--aws-region")
    value.add_argument(
        "--bedrock-model-id",
        default="openai.gpt-oss-20b-1:0",
    )
    value.add_argument("--max-output-tokens", type=int, default=300)
    return value


def main() -> None:
    args = parser().parse_args()
    payload = asyncio.run(
        evaluate_dataset(
            args.dataset,
            provider_name=args.provider,
            aws_region=args.aws_region,
            bedrock_model_id=args.bedrock_model_id,
            max_output_tokens=args.max_output_tokens,
        )
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")
    if not payload["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
