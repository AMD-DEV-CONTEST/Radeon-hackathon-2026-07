"""DataHub Context Client for Determinex.

Reads dataset schema, columns and lineage from DataHub's GraphQL API so generated
code can be checked against the real catalog instead of a guess.

PROVENANCE IS THE WHOLE POINT
-----------------------------
The pitch for this integration is "zero schema hallucination". The first version
of this client undermined exactly that: `_execute_gql` caught `URLError`/`OSError`
and silently returned built-in fixture data, and `get_dataset_schema` fell back to
fixtures on an empty response too. So with DataHub unreachable it produced an
invented five-column `analytics.orders`, printed "[OK] Fetched 5 fields", and the
generator emitted SQL against a schema that does not exist -- indistinguishable
from a real run.

Silently substituting invented schema is the worst possible failure for a tool
whose claim is that it does not invent schema. So:

  * Every result carries `provenance`: "live" or "fixture". Nothing is anonymous.
  * Fixtures are used only when explicitly requested (`mock_mode`). A network or
    transport failure raises `DataHubUnavailable` -- it never becomes data.
  * Callers that emit artifacts must stamp the provenance they actually got.

Fixtures still exist, because a judge cloning this repo needs to run it without
standing up a DataHub instance. They are just never a silent substitute.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

LIVE = "live"
FIXTURE = "fixture"


class DataHubUnavailable(RuntimeError):
    """DataHub could not be reached or answered with an error.

    Raised instead of returning fixture data, so a caller can never mistake
    invented schema for catalog truth.
    """


@dataclass
class DatasetSchema:
    """A dataset's schema plus where it came from."""

    urn: str
    name: str
    platform: str
    fields: list[dict[str, Any]] = field(default_factory=list)
    provenance: str = FIXTURE

    @property
    def is_live(self) -> bool:
        return self.provenance == LIVE

    def field_names(self) -> list[str]:
        return [f["name"] for f in self.fields]

    def has_field(self, name: str) -> bool:
        return name in self.field_names()


@dataclass
class Lineage:
    urn: str
    upstreams: list[str] = field(default_factory=list)
    provenance: str = FIXTURE


class DataHubContextClient:
    """Query and emit metadata to DataHub."""

    def __init__(
        self,
        gql_url: str | None = None,
        token: str | None = None,
        mock_mode: bool = False,
        timeout: int = 10,
    ):
        self.gql_url = gql_url or os.getenv("DATAHUB_GQL_URL", "http://localhost:8080/api/graphql")
        self.token = token or os.getenv("DATAHUB_PAT", "")
        self.mock_mode = mock_mode or os.getenv("DATAHUB_MOCK_MODE", "0") in ("1", "true")
        self.timeout = timeout

    # ── transport ────────────────────────────────────────────────────────────

    def _execute_gql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST a GraphQL document. Raises DataHubUnavailable rather than
        degrading to fixtures -- that decision belongs to the caller, explicitly."""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
        req = urllib.request.Request(self.gql_url, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise DataHubUnavailable(
                f"DataHub returned HTTP {exc.code} for {self.gql_url}"
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise DataHubUnavailable(f"could not reach DataHub at {self.gql_url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise DataHubUnavailable(f"DataHub returned non-JSON from {self.gql_url}") from exc

        # GraphQL reports failures in-band with HTTP 200, so an unchecked
        # response is not a successful one.
        if payload.get("errors"):
            msgs = "; ".join(e.get("message", "?") for e in payload["errors"])
            raise DataHubUnavailable(f"DataHub GraphQL error: {msgs}")
        return payload

    # ── reads ────────────────────────────────────────────────────────────────

    _SCHEMA_QUERY = """
    query getDatasetSchema($urn: String!) {
      dataset(urn: $urn) {
        urn
        name
        platform { name }
        schemaMetadata {
          fields {
            fieldPath
            nativeDataType
            description
            nullable
          }
        }
      }
    }
    """

    def get_dataset_schema(self, dataset_urn: str) -> DatasetSchema:
        if self.mock_mode:
            return self._fixture_schema(dataset_urn)

        payload = self._execute_gql(self._SCHEMA_QUERY, {"urn": dataset_urn})
        ds = (payload.get("data") or {}).get("dataset")
        if not ds:
            # A reachable catalog that does not know this URN is a real answer:
            # "no such dataset". Inventing one here is what caused the original
            # hallucination.
            raise DataHubUnavailable(f"DataHub has no dataset for urn {dataset_urn}")

        meta = ds.get("schemaMetadata") or {}
        fields = [
            {
                "name": f.get("fieldPath", ""),
                "type": f.get("nativeDataType", "VARCHAR"),
                "description": f.get("description") or "",
                "nullable": f.get("nullable", True),
            }
            for f in (meta.get("fields") or [])
        ]
        return DatasetSchema(
            urn=ds.get("urn", dataset_urn),
            name=ds.get("name", ""),
            platform=((ds.get("platform") or {}).get("name") or ""),
            fields=fields,
            provenance=LIVE,
        )

    def get_dataset_fields(self, dataset_urn: str) -> list[dict[str, Any]]:
        return self.get_dataset_schema(dataset_urn).fields

    # DataHub's searchAcrossLineage takes ONE `input` object of type
    # SearchAcrossLineageInput! (verified against docs.datahub.com/docs/graphql/
    # queries). The original version passed positional `urn:`/`direction:` args,
    # which is invalid GraphQL -- it would have failed against every real
    # instance, and the silent fixture fallback hid that completely.
    _LINEAGE_QUERY = """
    query getLineage($input: SearchAcrossLineageInput!) {
      searchAcrossLineage(input: $input) {
        searchResults {
          entity { urn type }
        }
      }
    }
    """

    def get_dataset_lineage(self, dataset_urn: str, direction: str = "UPSTREAM") -> Lineage:
        if self.mock_mode:
            return self._fixture_lineage(dataset_urn)

        payload = self._execute_gql(
            self._LINEAGE_QUERY,
            {"input": {"urn": dataset_urn, "direction": direction, "start": 0, "count": 100}},
        )
        results = ((payload.get("data") or {}).get("searchAcrossLineage") or {}).get(
            "searchResults"
        )
        if results is None:
            raise DataHubUnavailable(f"no lineage result for urn {dataset_urn}")
        upstreams: list[str] = []
        for r in results:
            urn = ((r or {}).get("entity") or {}).get("urn")
            if isinstance(urn, str) and urn:
                upstreams.append(urn)
        return Lineage(urn=dataset_urn, upstreams=upstreams, provenance=LIVE)

    # ── writes ───────────────────────────────────────────────────────────────

    _LINEAGE_MUTATION = """
    mutation updateLineage($input: UpdateLineageInput!) {
      updateLineage(input: $input)
    }
    """

    def emit_lineage(self, downstream_urn: str, upstream_urns: list[str]) -> bool:
        """Write lineage edges back to DataHub via the updateLineage mutation.

        This was previously `return True` with the comment "Simulated lineage
        emission" -- it did nothing, while the submission's demo script promised
        "show lineage emitted back to DataHub" and a test asserted the constant.
        A hard-coded True behind a passing test is exactly the shape of claim
        this project exists to reject.

        In mock_mode it returns False and says so: there is no instance to write
        to, and reporting success for a write that did not happen is the same
        lie in a smaller box.
        """
        if self.mock_mode:
            return False

        payload = self._execute_gql(
            self._LINEAGE_MUTATION,
            {
                "input": {
                    "edgesToAdd": [
                        {"downstreamUrn": downstream_urn, "upstreamUrn": u} for u in upstream_urns
                    ],
                    "edgesToRemove": [],
                }
            },
        )
        return bool((payload.get("data") or {}).get("updateLineage"))

    # ── fixtures (only ever reached deliberately) ────────────────────────────

    def _fixture_schema(self, urn: str) -> DatasetSchema:
        if "customer" in urn.lower():
            return DatasetSchema(
                urn=urn,
                name="analytics.customers",
                platform="snowflake",
                provenance=FIXTURE,
                fields=[
                    {
                        "name": "customer_id",
                        "type": "BIGINT",
                        "description": "Unique customer ID",
                        "nullable": False,
                    },
                    {
                        "name": "email",
                        "type": "VARCHAR(255)",
                        "description": "Customer email address",
                        "nullable": False,
                    },
                    {
                        "name": "country_code",
                        "type": "VARCHAR(10)",
                        "description": "ISO country code",
                        "nullable": True,
                    },
                    {
                        "name": "created_at",
                        "type": "TIMESTAMP_NTZ",
                        "description": "Account registration timestamp",
                        "nullable": False,
                    },
                ],
            )
        return DatasetSchema(
            urn=urn,
            name="analytics.orders",
            platform="snowflake",
            provenance=FIXTURE,
            fields=[
                {
                    "name": "order_id",
                    "type": "BIGINT",
                    "description": "Primary key order identifier",
                    "nullable": False,
                },
                {
                    "name": "customer_id",
                    "type": "BIGINT",
                    "description": "Foreign key to analytics.customers",
                    "nullable": False,
                },
                {
                    "name": "order_total_usd",
                    "type": "DECIMAL(12,2)",
                    "description": "Total order amount in USD",
                    "nullable": False,
                },
                {
                    "name": "status",
                    "type": "VARCHAR(50)",
                    "description": "Order status (COMPLETED, PENDING, CANCELLED)",
                    "nullable": False,
                },
                {
                    "name": "ordered_at",
                    "type": "TIMESTAMP_NTZ",
                    "description": "Timestamp when order was placed",
                    "nullable": False,
                },
            ],
        )

    def _fixture_lineage(self, urn: str) -> Lineage:
        return Lineage(
            urn=urn,
            upstreams=["urn:li:dataset:(urn:li:dataPlatform:postgres,raw_orders,PROD)"],
            provenance=FIXTURE,
        )
