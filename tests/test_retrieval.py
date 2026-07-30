from pathlib import Path

from copilot.fixtures import load_dataset
from copilot.retrieval import HybridRetriever

ROOT = Path(__file__).resolve().parents[1]


def test_retrieval_ranks_password_guidance_first() -> None:
    dataset = load_dataset(ROOT / "data/support-cases.json")
    results = HybridRetriever(dataset.articles).search(
        "Password reset failed with E401",
        limit=3,
    )

    assert results
    assert results[0].document_id == "A1"
    assert all(result.score > 0 for result in results)
