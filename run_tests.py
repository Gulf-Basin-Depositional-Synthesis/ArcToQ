import unittest
import os
import sys
from qgis.core import QgsApplication

# This is the master script for running all tests in the 'tests' directory.

if __name__ == '__main__':
    # Add the root project directory to the Python path
    sys.path.append(os.path.abspath(os.path.dirname(__file__)))

    print("Initializing QGIS application...")
    # Initialize QGIS Application - THIS IS CRUCIAL
    # We do it once here for the entire test suite.
    qgs = QgsApplication([], False)
    qgs.initQgis()

    # --- Test Discovery and Execution ---
    # Create a TestSuite to hold all discovered tests
    suite = unittest.TestSuite()

    # Create a TestLoader that will find our tests
    # It will discover all files in the 'tests' directory that start with 'test_'
    loader = unittest.TestLoader()
    tests = loader.discover('tests', pattern='test_*.py')
    
    # Add the discovered tests to our suite
    suite.addTests(tests)

    # --- Run the Tests ---
    # Create a TextTestRunner to execute the suite and print results
    runner = unittest.TextTestRunner(verbosity=2) # verbosity=2 gives detailed output
    print(f"Running {suite.countTestCases()} tests...")
    
    result = runner.run(suite)

    # --- Clean Up ---
    print("Exiting QGIS application.")
    qgs.exitQgis()
    
    # Exit with a non-zero status code if any tests failed
    if not result.wasSuccessful():
        sys.exit(1)