"""CRO batch 5: new vs returning customers. No network: Shopify is a fake GraphQL function."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from flowmerce.modules.cro import conversion, customers


@pytest.fixture(autouse=True)
def _clean_cache() -> Any:
    conversion.clear_cache()
    yield
    conversion.clear_cache()


def test_new_vs_returning_from_shopify() -> None:
    def gql(_q: str, v: dict[str, Any] | None = None) -> dict[str, Any]:
        q = str((v or {}).get("q"))
        if "returning_customer_rate" in q:
            rows: list[dict[str, Any]] = [{"returning_customer_rate": "0.219"}]
        else:
            rows = [
                {
                    "new_or_returning_customer": "New",
                    "orders": "1155",
                    "net_sales": "132952.55",
                    "average_order_value": "121.179",
                },
                {
                    "new_or_returning_customer": "Returning",
                    "orders": "342",
                    "net_sales": "31305.39",
                    "average_order_value": "92.555",
                },
            ]
        return {"shopifyqlQuery": {"parseErrors": None, "tableData": {"columns": [], "rows": rows}}}

    out = customers.new_vs_returning(
        "RBP",
        (date(2026, 10, 24), date(2026, 11, 20)),
        (date(2026, 9, 26), date(2026, 10, 23)),
        gql,
    )
    assert (
        out["orders"] == 1497
        and out["new"]["orders"] == 1155
        and out["new"]["share_of_orders"] == 77.2
    )
    assert out["returning"]["aov"] == 92.56 and out["returning_customer_rate"] == 21.9
    assert out["previous"]["returning"]["orders"] == 342
