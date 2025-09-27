import unittest
import os
import sys
import xml.etree.ElementTree as ET

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from arc_to_q.converters.lyrx_converter import convert_lyrx
from qgis.core import QgsApplication

class TestSymbology(unittest.TestCase):
    def run_conversion_and_parse(self, test_folder, lyrx_filename):
        """Helper to run conversion and return the parsed XML trees."""
        lyrx_path = os.path.join('tests', 'test_data', test_folder, lyrx_filename)
        output_folder = os.path.join('tests', 'output_qlr', test_folder)
        os.makedirs(output_folder, exist_ok=True)
        
        # FIX: Get the QGIS instance directly from the application
        convert_lyrx(lyrx_path, output_folder, QgsApplication.instance())

        generated_qlr_path = os.path.join(output_folder, lyrx_filename.replace('.lyrx', '.qlr'))
        expected_qlr_path = os.path.join('tests', 'expected_qlr', test_folder, lyrx_filename.replace('.lyrx', '.qlr'))

        return ET.parse(generated_qlr_path), ET.parse(expected_qlr_path)

    def test_unique_values_renderer_type(self):
        """Tests if the renderer for dummyfill.lyrx is 'categorized'."""
        generated_tree, _ = self.run_conversion_and_parse('polygon_unique_values', 'dummyfill.lyrx')
        renderer = generated_tree.find('.//renderer-v2')
        self.assertEqual(renderer.get('type'), 'categorizedSymbol')

    def test_unique_values_category_count(self):
        """Tests if the number of categories is correct."""
        generated_tree, expected_tree = self.run_conversion_and_parse('polygon_unique_values', 'dummyfill.lyrx')
        generated_categories = generated_tree.findall('.//renderer-v2/categories/category')
        expected_categories = expected_tree.findall('.//renderer-v2/categories/category')
        self.assertEqual(len(generated_categories), len(expected_categories))

    def test_unique_values_symbol_colors(self):
        """Tests if the symbol colors for each category are correct."""
        generated_tree, expected_tree = self.run_conversion_and_parse('polygon_unique_values', 'dummyfill.lyrx')
        
        def get_category_colors(categories):
            color_dict = {}
            for cat in categories:
                color_prop = cat.find('.//prop[@k="color"]')
                if color_prop is not None:
                    color_dict[cat.get('value')] = color_prop.get('v')
            return color_dict

        gen_colors = get_category_colors(generated_tree.findall('.//renderer-v2/categories/category'))
        exp_colors = get_category_colors(expected_tree.findall('.//renderer-v2/categories/category'))

        self.assertSetEqual(set(gen_colors.keys()), set(exp_colors.keys()))
        for value, expected_color in exp_colors.items():
            self.assertEqual(gen_colors[value], expected_color)