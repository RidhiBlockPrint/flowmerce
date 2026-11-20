"""Industry reference figures shown next to the store's own numbers.

These are widely cited e-commerce averages, not data from the store or a live API. Each carries its
source so the page can label it as a reference point.
"""

from __future__ import annotations

BENCHMARKS: dict[str, dict[str, object]] = {
    "cart_abandonment_rate": {
        "value": 70.0,
        "label": "Average online cart abandonment rate",
        "source": "Baymard Institute (commonly cited e-commerce average)",
    },
    "checkout_abandonment_rate": {
        "value": 69.0,
        "label": "Average checkout abandonment rate",
        "source": "Baymard Institute (commonly cited e-commerce average)",
    },
    "conversion_rate": {
        "value": 2.5,
        "label": "Average e-commerce conversion rate",
        "source": "Commonly cited e-commerce average (2-3% depending on sector)",
    },
}
