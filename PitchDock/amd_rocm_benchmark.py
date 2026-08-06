#!/usr/bin/env python3
"""
AMD Radeon GPU & ROCm Software Stack Benchmarking Tool for PitchDock AI.

Runs performance, throughput (tokens/sec), and latency benchmarking of PitchDock's
Agentic AI recruiter pitch generation engine accelerated on AMD Radeon GPUs with ROCm.
"""

import os
import sys
import time
import json
import rocm_inference

def print_header(title):
    print("\n" + "=" * 70)
    print(f"   {title}")
    print("=" * 70)

def main():
    print_header("AMD AI DevMaster Hackathon — PitchDock ROCm Benchmark")
    
    # 1. Hardware & Framework Diagnostics
    print("\n[1/3] Detecting AMD Acceleration Infrastructure...")
    hw_info = rocm_inference.get_amd_hardware_info()
    
    print(f"  • PyTorch Installed:   {hw_info['pytorch_installed']}")
    print(f"  • ROCm GPU Available:  {hw_info['rocm_available']}")
    print(f"  • Device Model:        {hw_info['device_name']}")
    print(f"  • Driver Stack:        {hw_info['rocm_version']}")
    print(f"  • Total VRAM:          {hw_info['vram_gb']} GB")
    print(f"  • Active Backend:      {hw_info['backend']}")

    # 2. Candidate & Recruiter Test Target Initialization
    print("\n[2/3] Initializing Agentic Outreach Generation Payload...")
    mock_contact = {
        "name": "Sarah Connor",
        "title": "Director of Talent Acquisition",
        "company": "AMD Advanced Systems",
        "email": "sarah.connor@amd.com",
        "target_role": "Senior Agentic AI Engineer"
    }
    
    mock_profile = {
        "full_name": "Shubranshu Shekhar",
        "target_role": "Senior Agentic AI Engineer",
        "experience_years": "3+",
        "achievements": [
            "Built distributed multi-agent LLM workflow engine processing 100k+ tasks/day with ROCm GPU acceleration.",
            "Optimized local model inference latency by 45% using AMD Radeon GPU HIP memory pooling."
        ]
    }

    # 3. Execution & Latency Benchmarking
    print("\n[3/3] Executing Pitch Generation on AMD ROCm Acceleration Stack...")
    start_time = time.time()
    
    subject, body, metrics = rocm_inference.generate_email_draft_rocm(mock_contact, mock_profile)
    
    total_latency = time.time() - start_time
    
    print_header("BENCHMARK RESULTS & AMD ROCm PERFORMANCE SUMMARY")
    print(f"  • Output Subject:     {subject}")
    print(f"  • Body Word Count:    {len(body.split())} words")
    print(f"  • Total Execution:    {metrics['execution_time_sec']} seconds")
    print(f"  • Inference Throughput: {metrics['tokens_per_sec']} tokens/second")
    print(f"  • Compute Backend:    {metrics['backend']} [{metrics['device']}]")
    print(f"  • Hackathon Track:    Track 2 - Agentic AI")
    print("=" * 70)
    print("\n✓ PitchDock AMD ROCm Local Inference & Agentic AI Benchmark Completed Successfully!\n")

if __name__ == "__main__":
    main()
