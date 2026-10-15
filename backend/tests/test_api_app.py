from tests.api_helpers import API, assert_error


def test_openapi_lists_only_versioned_phase3_paths(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert spec["info"]["title"] == "Race UP Test Data Manager"
    paths = set(spec["paths"])
    assert all(path.startswith(f"{API}/") for path in paths)
    assert paths == {
        f"{API}/seasons",
        f"{API}/seasons/{{season_id}}",
        f"{API}/vehicles",
        f"{API}/vehicles/{{vehicle_id}}",
        f"{API}/drivers",
        f"{API}/drivers/{{driver_id}}",
        f"{API}/track-locations",
        f"{API}/track-locations/{{location_id}}",
        f"{API}/track-layouts",
        f"{API}/track-layouts/{{layout_id}}",
        f"{API}/tests",
        f"{API}/tests/{{test_id}}",
        f"{API}/tests/{{test_id}}/planned-runs",
        f"{API}/planned-runs/{{planned_run_id}}",
        f"{API}/tests/{{test_id}}/runs",
        f"{API}/runs/{{run_id}}",
    }


def test_openapi_documents_the_standard_error_shape(client):
    spec = client.get("/openapi.json").json()
    create_test = spec["paths"][f"{API}/tests"]["post"]["responses"]
    for status_code in ("409", "422"):
        schema = create_test[status_code]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ErrorResponse"}
    assert "HTTPValidationError" not in spec["components"]["schemas"]


def test_swagger_ui_is_served(client):
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger" in response.text.lower()


def test_unversioned_path_is_not_routed(client):
    assert_error(client.get("/seasons"), 404, "not_found")


def test_unsupported_method_uses_standard_error_shape(client):
    assert_error(client.delete(f"{API}/seasons"), 405, "method_not_allowed")
