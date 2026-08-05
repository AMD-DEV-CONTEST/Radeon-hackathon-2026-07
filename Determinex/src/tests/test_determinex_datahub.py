"""Tests for the Determinex DataHub context client and code generator.

The previous version of this file had four tests, all constructed with
`mock_mode=True`. They asserted that the built-in fixture returned the fixture's
own contents -- e.g. `len(fields) == 5` -- and nothing exercised the real
GraphQL transport at all. One of them (`test_datahub_client_lineage`) passed only
because a silent fallback fired: in mock mode the response carried no
`searchAcrossLineage` key, so the code returned a hard-coded
`{"upstreams": [...]}`. The test proved the fallback existed, not that lineage
worked. A fifth asserted `emit_lineage(...) is True` against a method whose body
was literally `return True`.

So the suite was green and the integration was substantially broken. These tests
are built to fail for the reasons that matter:

  * a real HTTP server exercises the live transport, so query shape and parsing
    are actually checked;
  * the central guard is that an unreachable DataHub RAISES rather than yielding
    invented schema, because silent fabrication is the one failure that destroys
    this integration's entire claim;
  * the generator is checked against a schema WITHOUT the `status` column, which
    is the case the old hard-coded predicate produced invalid SQL for.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.determinex_data_engineer import generate_dbt_model  # noqa: E402
from scripts.determinex_datahub import (  # noqa: E402
    FIXTURE,
    LIVE,
    DataHubContextClient,
    DataHubUnavailable,
    DatasetSchema,
)

# ── a real (tiny) DataHub stand-in, so the live path is genuinely exercised ────


class _Handler(BaseHTTPRequestHandler):
    """Serves scripted GraphQL responses and records what it was asked."""

    scripted: dict = {}
    received: list = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).received.append(body)
        query = body.get("query", "")
        if "updateLineage" in query:
            payload = type(self).scripted.get("mutation", {"data": {"updateLineage": True}})
        elif "searchAcrossLineage" in query:
            payload = type(self).scripted.get(
                "lineage", {"data": {"searchAcrossLineage": {"searchResults": []}}}
            )
        else:
            payload = type(self).scripted.get("schema", {"data": {"dataset": None}})
        raw = json.dumps(payload).encode()
        self.send_response(payload.pop("_status", 200) if isinstance(payload, dict) else 200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # keep pytest output clean


@pytest.fixture
def stub_datahub():
    _Handler.scripted = {}
    _Handler.received = []
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/api/graphql"
    yield url, _Handler
    srv.shutdown()


LIVE_SCHEMA = {
    "data": {
        "dataset": {
            "urn": "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.orders,PROD)",
            "name": "analytics.orders",
            "platform": {"name": "snowflake"},
            "schemaMetadata": {
                "fields": [
                    {
                        "fieldPath": "order_id",
                        "nativeDataType": "BIGINT",
                        "description": "pk",
                        "nullable": False,
                    },
                    {
                        "fieldPath": "customer_id",
                        "nativeDataType": "BIGINT",
                        "description": "fk",
                        "nullable": False,
                    },
                ]
            },
        }
    }
}

ORDERS_URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.orders,PROD)"


# ── the guard that matters most ───────────────────────────────────────────────


def test_unreachable_datahub_raises_and_never_fabricates_schema():
    """The whole claim is 'zero schema hallucination'.

    The original client caught URLError/OSError and returned fixtures, so an
    unreachable catalog produced an invented five-column analytics.orders that
    looked identical to a real answer. That must be impossible.
    """
    client = DataHubContextClient(gql_url="http://127.0.0.1:59999/api/graphql")
    with pytest.raises(DataHubUnavailable):
        client.get_dataset_schema(ORDERS_URN)


def test_graphql_inband_errors_raise(stub_datahub):
    """GraphQL reports failures with HTTP 200 and an `errors` array, so an
    unchecked 200 is not a success."""
    url, handler = stub_datahub
    handler.scripted["schema"] = {"errors": [{"message": "Unknown field 'nope'"}]}
    client = DataHubContextClient(gql_url=url)
    with pytest.raises(DataHubUnavailable, match="Unknown field"):
        client.get_dataset_schema(ORDERS_URN)


def test_unknown_urn_raises_rather_than_inventing_a_dataset(stub_datahub):
    url, handler = stub_datahub
    handler.scripted["schema"] = {"data": {"dataset": None}}
    client = DataHubContextClient(gql_url=url)
    with pytest.raises(DataHubUnavailable, match="no dataset"):
        client.get_dataset_schema(ORDERS_URN)


# ── live path ─────────────────────────────────────────────────────────────────


def test_live_schema_is_parsed_and_marked_live(stub_datahub):
    url, handler = stub_datahub
    handler.scripted["schema"] = LIVE_SCHEMA
    client = DataHubContextClient(gql_url=url)
    schema = client.get_dataset_schema(ORDERS_URN)

    assert schema.provenance == LIVE and schema.is_live
    assert schema.name == "analytics.orders"
    assert schema.field_names() == ["order_id", "customer_id"]
    # fieldPath -> name and nativeDataType -> type must actually be mapped.
    assert schema.fields[0]["type"] == "BIGINT"


def test_lineage_query_sends_a_single_input_object(stub_datahub):
    """DataHub's searchAcrossLineage takes one `input: SearchAcrossLineageInput!`.

    The original query used positional `urn:`/`direction:` args -- invalid
    GraphQL that would fail against every real instance, hidden by the fallback.
    """
    url, handler = stub_datahub
    handler.scripted["lineage"] = {
        "data": {
            "searchAcrossLineage": {
                "searchResults": [{"entity": {"urn": "urn:li:dataset:up", "type": "DATASET"}}]
            }
        }
    }
    client = DataHubContextClient(gql_url=url)
    lineage = client.get_dataset_lineage(ORDERS_URN)

    assert lineage.upstreams == ["urn:li:dataset:up"]
    assert lineage.provenance == LIVE
    sent = handler.received[-1]
    assert "$input: SearchAcrossLineageInput!" in sent["query"]
    assert sent["variables"]["input"]["urn"] == ORDERS_URN
    assert sent["variables"]["input"]["direction"] == "UPSTREAM"


def test_emit_lineage_actually_calls_updateLineage(stub_datahub):
    """Was `return True` with the comment "Simulated lineage emission" -- a
    hard-coded constant behind a passing test, while the demo script promised
    lineage was emitted."""
    url, handler = stub_datahub
    handler.scripted["mutation"] = {"data": {"updateLineage": True}}
    client = DataHubContextClient(gql_url=url)

    assert client.emit_lineage("urn:li:dataset:down", ["urn:li:dataset:up"]) is True
    sent = handler.received[-1]
    assert "updateLineage" in sent["query"]
    assert sent["variables"]["input"]["edgesToAdd"] == [
        {"downstreamUrn": "urn:li:dataset:down", "upstreamUrn": "urn:li:dataset:up"}
    ]


def test_emit_lineage_reports_false_in_mock_mode():
    """There is no instance to write to, so claiming success is the same lie in
    a smaller box."""
    assert DataHubContextClient(mock_mode=True).emit_lineage("a", ["b"]) is False


# ── fixtures are allowed, but never anonymous ──────────────────────────────────


def test_fixture_mode_is_labelled_fixture_not_live():
    client = DataHubContextClient(mock_mode=True)
    schema = client.get_dataset_schema(ORDERS_URN)
    assert schema.provenance == FIXTURE
    assert not schema.is_live
    assert "customer_id" in schema.field_names()


# ── generator ─────────────────────────────────────────────────────────────────


def _schema(name: str, cols: list[str], provenance: str = LIVE) -> DatasetSchema:
    return DatasetSchema(
        urn=f"urn:li:dataset:{name}",
        name=name,
        platform="snowflake",
        provenance=provenance,
        fields=[{"name": c, "type": "VARCHAR", "description": "", "nullable": True} for c in cols],
    )


def test_generator_omits_the_status_filter_when_the_column_does_not_exist():
    """The original emitted `where o.status != 'CANCELLED'` unconditionally.
    `status` exists only in the fixture, so against a real schema without it the
    "schema-verified" output was invalid SQL."""
    sql = generate_dbt_model(
        _schema("analytics.orders", ["order_id", "customer_id"]),
        _schema("analytics.customers", ["customer_id", "email"]),
    )
    assert "status" not in sql
    assert "where" not in sql.lower()


def test_generator_includes_the_status_filter_when_the_column_exists():
    sql = generate_dbt_model(
        _schema("analytics.orders", ["order_id", "customer_id", "status"]),
        _schema("analytics.customers", ["customer_id", "email"]),
    )
    assert "where o.status != 'CANCELLED'" in sql


def test_generator_refuses_when_the_join_key_is_absent():
    with pytest.raises(ValueError, match="customer_id"):
        generate_dbt_model(
            _schema("analytics.orders", ["order_id"]),
            _schema("analytics.customers", ["customer_id"]),
        )


def test_generated_sql_states_which_source_it_came_from():
    live = generate_dbt_model(
        _schema("o", ["order_id", "customer_id"]),
        _schema("c", ["customer_id", "email"]),
    )
    assert "DataHub live catalog" in live

    fixture = generate_dbt_model(
        _schema("o", ["order_id", "customer_id"], FIXTURE),
        _schema("c", ["customer_id", "email"], FIXTURE),
    )
    # A fixture-derived artifact must be impossible to mistake for a verified one.
    assert "OFFLINE FIXTURES" in fixture
    assert "not verified" in fixture
