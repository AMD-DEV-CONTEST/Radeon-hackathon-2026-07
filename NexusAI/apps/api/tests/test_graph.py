from fastapi.testclient import TestClient
from app.main import app
def test_graph():
 with TestClient(app) as c:
  w=c.post("/api/worlds",json={"name":"Graph Test","world_type":"worldforge"}).json()
  a=c.post(f"/api/worlds/{w['id']}/entities",json={"entity_type":"character","name":"Hero"}).json()
  b=c.post(f"/api/worlds/{w['id']}/entities",json={"entity_type":"kingdom","name":"Northrealm"}).json()
  r=c.post(f"/api/worlds/{w['id']}/relationships",json={"source_entity_id":a["id"],"target_entity_id":b["id"],"relationship_type":"RULES"})
  assert r.status_code==201
  g=c.get(f"/api/worlds/{w['id']}/graph").json()
  assert len(g["nodes"])==2 and len(g["edges"])==1


def test_worldforge_data():
 with TestClient(app) as c:
  w=c.post("/api/worlds",json={"name":"WorldForge Data","world_type":"worldforge"}).json()
  a=c.post(f"/api/worlds/{w['id']}/entities",json={"entity_type":"person","name":"Aria"}).json()
  b=c.post(f"/api/worlds/{w['id']}/entities",json={"entity_type":"place","name":"Kochi"}).json()
  c.post(f"/api/worlds/{w['id']}/relationships",json={"source_entity_id":a["id"],"target_entity_id":b["id"],"relationship_type":"LIVES_IN"})
  data=c.get(f"/api/worlds/{w['id']}/worldforge")
  assert data.status_code==200
  body=data.json()
  assert len(body["entities"])==2
  assert len(body["relationships"])==1
  aria=next(e for e in body["entities"] if e["name"]=="Aria")
  assert aria["connection_count"]==1
