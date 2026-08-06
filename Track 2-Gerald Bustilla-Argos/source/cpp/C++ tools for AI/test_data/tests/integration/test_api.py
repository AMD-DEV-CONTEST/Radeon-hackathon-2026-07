import requests

def test_login_endpoint():
    response = requests.post('http://localhost:8080/api/auth/login',
        json={'username': 'admin', 'password': 'admin'})
    assert response.status_code == 200
    assert 'token' in response.json()

def test_search_endpoint():
    response = requests.get('http://localhost:8080/api/search',
        params={'query': 'authentication'})
    assert response.status_code == 200
    assert len(response.json()['results']) > 0
