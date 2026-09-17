# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from ifind_sector_hub.codes import is_a_share_code, is_a_share_concept


class CodesTests(unittest.TestCase):
    def test_a_share_code(self):
        self.assertTrue(is_a_share_code("600519.SH"))
        self.assertTrue(is_a_share_code("000001.SZ"))
        self.assertTrue(is_a_share_code("430047.BJ"))
        self.assertFalse(is_a_share_code("AAPL.US"))
        self.assertFalse(is_a_share_code(None))

    def test_a_share_concept(self):
        for pfx in ("700", "881", "883", "884", "885", "886"):
            self.assertTrue(is_a_share_concept(pfx + "001.TI"), pfx)
        # 海外前缀（spec：861/864/865/871/875 必须排除）
        for pfx in ("861", "864", "865", "871", "875"):
            self.assertFalse(is_a_share_concept(pfx + "001.TI"), pfx)
        self.assertFalse(is_a_share_concept(None))


if __name__ == "__main__":
    unittest.main()
