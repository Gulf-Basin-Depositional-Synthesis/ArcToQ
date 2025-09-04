from arc_to_q.converters.lyrx_converter import LyrxConverter
from arc_to_q.converters.aprx_converter import AprxConverter

def main():
    # Placeholder paths
    lyrx_path = "resources/sample_inputs/sample.lyrx"
    aprx_path = "resources/sample_inputs/sample.aprx"

    # Convert LYRX
    lyrx_converter = LyrxConverter(lyrx_path)
    lyrx_converter.convert()

    # Convert APRX
    aprx_converter = AprxConverter(aprx_path)
    aprx_converter.convert()

if __name__ == "__main__":
    main()