"""
AutoSec Agent — Test Suite
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_imports():
    """Test all modules import correctly"""
    try:
        from core.agent import AutoSecAgent
        from ai.analyzer import ROCmAccelerator
        from reporting.email_reporter import EmailReporter
        from reporting.notion_reporter import NotionReporter
        print("[✓] All modules imported successfully")
        return True
    except Exception as e:
        print(f"[✗] Import failed: {e}")
        return False

def test_agent_init():
    """Test agent initialization"""
    from core.agent import AutoSecAgent
    agent = AutoSecAgent(verbose=False)
    assert agent is not None
    assert hasattr(agent, 'scan_target')
    assert hasattr(agent, 'run_full_scan')
    print("[✓] Agent initialized successfully")
    return True

def test_config():
    """Test configuration loads"""
    from config.settings import Config
    assert Config.SUBFINDER_PATH
    assert Config.NUCLEI_PATH
    assert Config.OUTPUT_DIR
    print("[✓] Config loaded successfully")
    return True

def test_report_generation():
    """Test report generation without real scan"""
    from core.agent import AutoSecAgent
    from datetime import datetime
    
    agent = AutoSecAgent(verbose=False)
    agent.target = "test.target"
    agent.start_time = 0
    agent.results = {
        "target": "test.target",
        "phases": {
            "subdomains": ["sub1.test.target", "sub2.test.target"],
            "live_hosts": ["https://sub1.test.target:443"],
            "vulnerabilities": [
                {"info": {"name": "Test Vuln", "severity": "high"}}
            ],
            "ai_analysis": {
                "risk_score": 42, "risk_level": "MEDIUM",
                "recommendations": ["Test recommendation"]
            }
        }
    }
    report = agent.generate_report()
    assert report is not None
    assert "test.target" in report
    assert "AutoSec Agent" in report
    print("[✓] Report generation works")
    return True

if __name__ == "__main__":
    print("=== AutoSec Agent Test Suite ===\n")
    tests = [test_imports, test_agent_init, test_config, test_report_generation]
    passed = sum(1 for t in tests if t())
    total = len(tests)
    print(f"\n=== {passed}/{total} tests passed ===")
