from app.routes.worlds import router

def test_blueprint_route_is_registered():
    paths={route.path for route in router.routes}
    assert "/worlds/{world_id}/blueprint" in paths
