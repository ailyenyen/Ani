import calendar
import json
from datetime import date
from unittest import TestCase
from unittest.mock import Mock

from scrapers.psa_farmgate import REGION_CODE, fetch_banana_farmgate


class FarmgateSourceTests(TestCase):
    def test_uses_psa_labels_and_preserves_available_past_months(self):
        labels = {
            "Geolocation": (["..REGION IV-A (CALABARZON)"], [REGION_CODE]),
            "Commodity": (["Banana Lakatan, green", "Banana Latundan, green", "Banana Saba, green"], ["a", "b", "c"]),
            "Year": (["2026"], ["current"]),
            "Period": (list(calendar.month_name)[1:], [str(i) for i in range(1, 13)]),
        }
        metadata = {"variables": [
            {"code": key, "valueTexts": names, "values": codes} for key, (names, codes) in labels.items()
        ]}
        result = {"columns": [{"code": key, "type": "d"} for key in reversed(labels)], "data": [
            {"key": ["6", "current", "a", REGION_CODE], "values": ["45.25"]},
            {"key": ["7", "current", "a", REGION_CODE], "values": [".."]},
            {"key": ["11", "current", "b", REGION_CODE], "values": ["35.00"]},
        ]}
        session = Mock()
        session.get.return_value.content = json.dumps(metadata).encode("utf-8")
        session.post.return_value.content = json.dumps(result).encode("utf-8-sig")
        self.assertEqual(fetch_banana_farmgate(session, date(2026, 11, 19)), [
            {"variety": "Lakatan", "month": "2026-06-01", "price": "45.25"},
        ])
        self.assertIn({"code": "Commodity", "selection": {"filter": "item", "values": ["a", "b", "c"]}},
                      session.post.call_args.kwargs["json"]["query"])
