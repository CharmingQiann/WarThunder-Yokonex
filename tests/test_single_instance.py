from __future__ import annotations

import uuid
import unittest

from war_thunder_yokonex.single_instance import SingleInstance


class SingleInstanceTests(unittest.TestCase):
    def test_second_instance_is_rejected_until_first_closes(self) -> None:
        name = f"Local\\WarThunder-Yokonex-Test-{uuid.uuid4().hex}"
        first = SingleInstance(name)
        second = SingleInstance(name)
        try:
            self.assertTrue(first.acquired)
            self.assertFalse(second.acquired)
        finally:
            second.close()
            first.close()

        third = SingleInstance(name)
        try:
            self.assertTrue(third.acquired)
        finally:
            third.close()


if __name__ == "__main__":
    unittest.main()
