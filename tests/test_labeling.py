import unittest
import os
import sys
import xml.etree.ElementTree as ET

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from arc_to_q.converters.lyrx_converter import convert_lyrx
from qgis.core import QgsApplication

class TestLabeling(unittest.TestCase):
    def setUp(self):
        """This method runs ONCE before EACH test in this class."""
        lyrx_path = os.path.join('tests', 'test_data', 'simple_points', 'dummy.lyrx')
        output_folder = os.path.join('tests', 'output_qlr', 'simple_points')
        os.makedirs(output_folder, exist_ok=True)

        # FIX: Get the QGIS instance directly from the application
        convert_lyrx(lyrx_path, output_folder, QgsApplication.instance())

        generated_qlr_path = os.path.join(output_folder, 'dummy.qlr')
        expected_qlr_path = os.path.join('tests', 'expected_qlr', 'simple_points', 'dummy.qlr')

        self.generated_tree = ET.parse(generated_qlr_path)
        self.expected_tree = ET.parse(expected_qlr_path)

    def test_labeling_is_enabled(self):
        """Tests if the labeling element exists and is enabled."""
        generated_labeling = self.generated_tree.find('.//labeling')
        self.assertIsNotNone(generated_labeling)
        self.assertEqual(generated_labeling.get('type'), 'simple')

    def test_label_expression(self):
        """Tests if the label text expression is correct."""
        generated_exp = self.generated_tree.find('.//labeling/settings/text-style').get('fieldName')
        expected_exp = self.expected_tree.find('.//labeling/settings/text-style').get('fieldName')
        self.assertEqual(generated_exp, expected_exp)

    def test_label_font_and_size(self):
        """Tests if the label font and size are correct."""
        generated_style = self.generated_tree.find('.//labeling/settings/text-style')
        expected_style = self.expected_tree.find('.//labeling/settings/text-style')
        self.assertEqual(generated_style.get('fontFamily'), expected_style.get('fontFamily'))
        self.assertEqual(generated_style.get('fontSize'), expected_style.get('fontSize'))