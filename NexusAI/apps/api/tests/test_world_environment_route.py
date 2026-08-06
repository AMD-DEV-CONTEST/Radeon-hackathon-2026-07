from app.routes.world_environment import router

def test_render_spec_route_is_registered():
    paths={route.path for route in router.routes}
    assert "/worlds/{world_id}/render-spec" in paths
