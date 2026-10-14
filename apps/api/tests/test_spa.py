from __future__ import annotations


def test_client_route_returns_index(make_client):
    response = make_client().get("/tasks")
    assert response.status_code == 200
    assert "mac-control" in response.text


def test_root_returns_index(make_client):
    assert "mac-control" in make_client().get("/").text


def test_assets_served(make_client):
    response = make_client().get("/assets/app.js")
    assert response.status_code == 200
    assert "console.log" in response.text


def test_root_level_file_served(make_client):
    assert make_client().get("/favicon.svg").text == "<svg/>"


def test_unknown_api_path_is_json_404(make_client):
    response = make_client().get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_lookalike_path_is_not_treated_as_api(make_client):
    # "/apiary" is a client route, not an API path.
    response = make_client().get("/apiary")
    assert response.status_code == 200
    assert "mac-control" in response.text


def test_traversal_outside_dist_returns_index_not_file(make_client, tmp_path):
    (tmp_path / "secret.txt").write_text("do not serve")
    response = make_client().get("/%2e%2e/secret.txt")
    assert "do not serve" not in response.text


def test_missing_build_returns_503(make_client):
    response = make_client(built=False).get("/tasks")
    assert response.status_code == 503
    assert "not built" in response.json()["detail"]
