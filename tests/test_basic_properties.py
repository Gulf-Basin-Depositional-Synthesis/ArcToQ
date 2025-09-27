import unittest
import os
import sys
import xml.etree.ElementTree as ET

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from arc_to_q.converters.lyrx_converter import convert_lyrx
from qgis.core import QgsApplication

class TestBasicProperties(unittest.TestCase):
    def run_conversion_and_parse(self, test_folder, lyrx_filename='dummy.lyrx'):
        """Helper to run conversion and return the parsed XML trees."""
        lyrx_path = os.path.join('tests', 'test_data', test_folder, lyrx_filename)
        output_folder = os.path.join('tests', 'output_qlr', test_folder)
        os.makedirs(output_folder, exist_ok=True)
        
        # FIX: Get the QGIS instance directly from the application
        convert_lyrx(lyrx_path, output_folder, QgsApplication.instance())

        generated_qlr_path = os.path.join(output_folder, lyrx_filename.replace('.lyrx', '.qlr'))
        expected_qlr_path = os.path.join('tests', 'expected_qlr', test_folder, lyrx_filename.replace('.lyrx', '.qlr'))

        return ET.parse(generated_qlr_path), ET.parse(expected_qlr_path)

    def test_simple_points_layer_name(self):
        """Tests if the layer name from dummy.lyrx is correctly written."""
        generated_tree, expected_tree = self.run_conversion_and_parse('simple_points')
        generated_name = generated_tree.find('.//layer-tree-layer').get('name')
        expected_name = expected_tree.find('.//layer-tree-layer').get('name')
        self.assertEqual(generated_name, expected_name)

    def test_simple_points_layer_visibility(self):
        """Tests if the layer visibility (checked state) is correctly set."""
        generated_tree, expected_tree = self.run_conversion_and_parse('simple_points')
        generated_visibility = generated_tree.find('.//layer-tree-layer').get('checked')
        expected_visibility = expected_tree.find('.//layer-tree-layer').get('checked')
        self.assertEqual(generated_visibility, expected_visibility)

    def test_polygon_unique_values_layer_name(self):
        """Tests if the layer name from dummyfill.lyrx is correct."""
        generated_tree, expected_tree = self.run_conversion_and_parse('polygon_unique_values', 'dummyfill.lyrx')
        generated_name = generated_tree.find('.//layer-tree-layer').get('name')
        expected_name = expected_tree.find('.//layer-tree-layer').get('name')
        self.assertEqual(generated_name, expected_name)