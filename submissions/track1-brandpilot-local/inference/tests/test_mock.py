from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1]))
from mock_pipeline import MockCampaignPipeline

def test_mock_pipeline_discloses_mode():
    pipeline = MockCampaignPipeline()
    assert pipeline.health_check()["gpu_connected"] is False
    assert "without AMD Radeon inference" in pipeline.analyze_product(Path("placeholder.png"))["disclosure"]
