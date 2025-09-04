import unittest
from arc_to_q.converters.lyrx_converter import LyrxConverter

class TestLyrxConverter(unittest.TestCase):
    def test_basic_conversion(self):
        converter = LyrxConverter("resources/sample_inputs/sample.lyrx")
        self.assertIsNotNone(converter.lyrx_path)