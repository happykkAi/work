import unittest

try:
    from tools.work.inventory import normalize_inventory
except ImportError as exc:
    normalize_inventory = None
    _import_error = exc
else:
    _import_error = None


class InventoryTests(unittest.TestCase):
    def test_inventory_marks_missing_evidence_unknown(self):
        self.assertIsNotNone(
            normalize_inventory,
            f"inventory implementation is missing: {_import_error}",
        )

        report = normalize_inventory({"production": {"organization_count": 0}})

        self.assertEqual(report["production"]["application_sha"], "UNKNOWN")
        self.assertEqual(report["production"]["migration_ledger"], "UNKNOWN")
        self.assertEqual(report["production"]["organization_count"], 0)
        self.assertEqual(report["production"]["data_bytes"], "UNKNOWN")

    def test_inventory_does_not_emit_unapproved_text(self):
        report = normalize_inventory(
            {
                "production": {
                    "application_sha": "secret-token-value",
                    "admin_recovery_path": "/private/account/identifier",
                }
            }
        )

        self.assertEqual(report["production"]["application_sha"], "UNKNOWN")
        self.assertEqual(report["production"]["admin_recovery_path"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
