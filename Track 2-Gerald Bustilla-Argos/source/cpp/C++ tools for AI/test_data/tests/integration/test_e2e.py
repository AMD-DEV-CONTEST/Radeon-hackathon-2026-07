import subprocess
import json

def test_full_search_workflow():
    result = subprocess.run(['./aisearch', 'index', './test_data'], capture_output=True)
    assert result.returncode == 0
    
    result = subprocess.run(['./aisearch', 'search', './test_data', '--query', 'auth'], capture_output=True)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data['total_hits'] > 0
