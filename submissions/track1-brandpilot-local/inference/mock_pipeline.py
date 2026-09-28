"""Honest mock implementation; it never claims model or GPU work occurred."""
from pathlib import Path
from typing import Any
from model_interface import CampaignPipeline

DISCLOSURE = "Mock output generated without AMD Radeon inference."

class MockCampaignPipeline(CampaignPipeline):
    def analyze_product(self, image_path: Path) -> dict[str, Any]:
        return {"mode":"mock","analysis":None,"disclosure":DISCLOSURE}
    def generate_creative_concept(self, analysis: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
        return {"mode":"mock","concept":"Placeholder creative concept","disclosure":DISCLOSURE}
    def generate_ad_image(self, image_path: Path, concept: dict[str, Any], output_format: str) -> dict[str, Any]:
        return {"mode":"mock","image_path":None,"output_format":output_format,"disclosure":DISCLOSURE}
    def generate_campaign_copy(self, concept: dict[str, Any], brief: dict[str, Any]) -> dict[str, str]:
        return {"headline":"Mock campaign headline","caption":"Mock campaign caption","call_to_action":"Learn more","disclosure":DISCLOSURE}
    def get_device_metrics(self) -> dict[str, Any]:
        return {"gpu_connected":False,"rocm_available":False,"device":None,"message":"No device metrics are reported in mock mode."}
    def health_check(self) -> dict[str, Any]:
        return {"status":"ok","mode":"mock","gpu_connected":False}
