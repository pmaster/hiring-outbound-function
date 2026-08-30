"""Manual providers. The pipeline still runs, a person does the step.

`manual` search means: `outbound search` prints the queries, you build the list
in the browser, and you import a CSV. That is the SOP's default for the senior
seats, because reading the profile by hand is the whole edge.
"""

from __future__ import annotations

from typing import Any

from ..errors import OutboundError
from . import register


class ManualSearch:
    name = "manual"

    def __init__(self, settings: Any = None):
        self.settings = settings

    def search(self, spec: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        raise OutboundError(
            "providers.search is 'manual'. Run `outbound search <role>` to print "
            "the queries, build the list by hand, then `outbound import <role> "
            "<file.csv>`."
        )


class ManualBooking:
    name = "manual"

    def __init__(self, settings: Any = None):
        self.settings = settings

    def list_bookings(self, since: str | None = None) -> list[dict[str, Any]]:
        raise OutboundError(
            "providers.booking is 'manual'. Export bookings from your scheduler "
            "and run `outbound bookings import <file.csv>`."
        )

    def cancel(self, provider_id: str, reason: str) -> bool:
        raise OutboundError(
            f"providers.booking is 'manual'. Cancel {provider_id} in the scheduler "
            f"by hand, then run `outbound bookings mark {provider_id} cancelled`."
        )


register("search", "manual")(ManualSearch)
register("booking", "manual")(ManualBooking)
