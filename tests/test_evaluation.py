from pathlib import Path

from copilot.config import Settings
from copilot.evaluation import evaluate
from copilot.fixtures import load_dataset, support_cases
from copilot.retrieval import HybridRetriever
from copilot.service import CopilotService
from copilot.storage import MemoryStore

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/support-cases.json"


async def test_golden_evaluation_passes() -> None:
    dataset = load_dataset(DATASET)
    store = MemoryStore()
    await store.replace_seed(dataset.articles, support_cases(dataset))
    service = CopilotService(
        Settings(environment="test", dataset_path=DATASET),
        store,
        HybridRetriever(dataset.articles),
    )

    report = await evaluate(dataset, service)

    assert report.passed
    assert report.provider == "deterministic-grounded-v1"
    assert report.route_accuracy == 1.0
    assert report.citation_recall >= report.thresholds["citation_recall"]
    assert report.risk_recall == 1.0
    assert report.unsafe_draft_rate == 0.0
    assert report.grounded_draft_rate == 1.0
    assert report.review_gate_rate == 1.0
    assert report.sensitive_data_leak_rate == 0.0
    assert report.route_counts == {"block": 3, "draft": 28, "escalate": 9}
    assert report.latency_ms_p95 >= report.latency_ms_p50 >= 0
    for case in support_cases(dataset):
        assert await store.get_suggestion(case.id) is None
    assert store.audit == []
