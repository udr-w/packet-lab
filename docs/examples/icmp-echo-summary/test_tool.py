import unittest

import tool


class TestSummarise(unittest.TestCase):
    def test_all_received(self):
        out = "2 packets transmitted, 2 received, 0% packet loss"
        self.assertEqual(tool.summarise(out),
                         {"transmitted": 2, "received": 2, "loss_percent": 0.0})

    def test_partial_loss(self):
        out = "4 packets transmitted, 3 received, 25% packet loss"
        result = tool.summarise(out)
        self.assertEqual(result["received"], 3)
        self.assertEqual(result["loss_percent"], 25.0)

    def test_no_match(self):
        self.assertEqual(tool.summarise("garbage")["transmitted"], 0)


if __name__ == "__main__":
    unittest.main()
