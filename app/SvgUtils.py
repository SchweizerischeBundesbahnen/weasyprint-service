import base64
import logging
import math
import os
import re
import subprocess
import tempfile
from uuid import uuid4

IMAGE_PNG = 'image/png'
IMAGE_SVG = 'image/svg+xml'

NON_SVG_CONTENT_TYPES = ('image/jpeg', 'image/png', 'image/gif')


# Process img tags, replacing base64 SVG images with PNGs
def process_svg(html):
    pattern = re.compile(r'<img(?P<intermediate>[^>]+?src="data:)(?P<type>[^;>]*?);base64,\s?(?P<base64>[^">]*?)"')
    return re.sub(pattern, replace_img_base64, html)


# Decode and validate if the provided content is SVG.
def get_svg_content(content_type, content_base64):
    # We do not require to have 'image/svg+xml' content type coz not all systems will properly set it

    if content_type in NON_SVG_CONTENT_TYPES:
        return None  # Skip processing if content type set explicitly as not svg

    try:
        decoded_content = base64.b64decode(content_base64)
        if b'\0' in decoded_content:
            return None  # Skip processing if decoded content is binary (not text)

        svg_content = decoded_content.decode('utf-8')

        # Fast check that this is a svg
        if '</svg>' not in svg_content:
            return None

        return svg_content
    except Exception as e:
        logging.error(f"Failed to decode base64 content: {e}")
        return None


# Replace base64 SVG images with PNG equivalents in the HTML img tag.
def replace_img_base64(match):
    entry = match.group(0)
    content_type = match.group('type')
    content_base64 = match.group('base64')

    svg_content = get_svg_content(content_type, content_base64)
    if not svg_content:
        return entry

    image_type, content = replace_svg_with_png(svg_content)
    replaced_content_base64 = to_base64(content)
    if replaced_content_base64 == content_base64:
        return entry  # For some reason content wasn't replaced

    return f'<img{match.group("intermediate")}{image_type};base64,{replaced_content_base64}"'


# Checks that base64 encoded content is a svg image and replaces it with the png screenshot made by chromium
def replace_svg_with_png(svg_content):
    width, height = extract_svg_dimensions_as_px(svg_content)
    if not width or not height:
        return IMAGE_SVG, svg_content

    svg_filepath, png_filepath = prepare_temp_files(svg_content)
    if not svg_filepath or not png_filepath:
        return IMAGE_SVG, svg_content

    if not convert_svg_to_png(width, height, png_filepath, svg_filepath):
        return IMAGE_SVG, svg_content

    png_content = read_and_cleanup_png(png_filepath)
    if not png_content:
        return IMAGE_SVG, svg_content

    return IMAGE_PNG, png_content


# Extract the width and height from the SVG tag (and convert it to px)
def extract_svg_dimensions_as_px(svg_content):
    width_match = re.search(r'<svg[^>]+?width="(?P<width>[\d.]+)(?P<unit>\w+)?', svg_content)
    height_match = re.search(r'<svg[^>]+?height="(?P<height>[\d.]+)(?P<unit>\w+)?', svg_content)

    width = width_match.group('width') if width_match else None
    height = height_match.group('height') if height_match else None

    if not width or not height:
        logging.error(f"Cannot find SVG dimensions. Width: {width}, Height: {height}")

    width_unit = width_match.group('unit') if width_match else None
    height_unit = height_match.group('unit') if height_match else None

    return convert_to_px(width, width_unit), convert_to_px(height, height_unit)


# Save the SVG content to a temporary file and return the file paths for the SVG and PNG.
def prepare_temp_files(svg_content):
    try:
        temp_folder = tempfile.gettempdir()
        uuid = str(uuid4())

        svg_filepath = os.path.join(temp_folder, f'{uuid}.svg')
        png_filepath = os.path.join(temp_folder, f'{uuid}.png')

        with open(svg_filepath, 'w', encoding='utf-8') as f:
            f.write(svg_content)

        return svg_filepath, png_filepath
    except Exception as e:
        logging.error(f"Failed to save SVG to temp file: {e}")
        return None, None


# Convert the SVG file to PNG using Chromium and return success status
def convert_svg_to_png(width, height, png_filepath, svg_filepath):
    command = create_chromium_command(width, height, png_filepath, svg_filepath)
    if not command:
        return False

    try:
        result = subprocess.run(command)
        if result.returncode != 0:
            logging.error(f"Error converting SVG to PNG, return code = {result.returncode}")
            return False
        return True
    except Exception as e:
        logging.error(f"Failed to convert SVG to PNG: {e}")
        return False


# Read the PNG file and clean up the temporary file
def read_and_cleanup_png(png_filepath):
    try:
        with open(png_filepath, 'rb') as img_file:
            img_data = img_file.read()

        os.remove(png_filepath)
        return img_data
    except Exception as e:
        logging.error(f"Failed to read or clean up PNG file: {e}")
        return None


# Create the Chromium command for converting SVG to PNG
def create_chromium_command(width, height, png_filepath, svg_filepath):
    chromium_executable = os.environ.get('CHROMIUM_EXECUTABLE_PATH')
    if not chromium_executable:
        logging.error('CHROMIUM_EXECUTABLE_PATH is not set.')
        return None

    command = [
        chromium_executable,
        '--headless=old',
        '--no-sandbox',
        '--disable-gpu',
        '--disable-software-rasterizer',
        '--disable-dev-shm-usage',
        '--default-background-color=00000000',
        '--hide-scrollbars',
        '--enable-features=ConversionMeasurement,AttributionReportingCrossAppWeb',
        f'--screenshot={png_filepath}',
        f'--window-size={width},{height}',
        svg_filepath,
    ]

    return command


# Encode string or byte array to base64
def to_base64(content):
    if isinstance(content, str):
        content = content.encode('utf-8')  # encode the string to bytes
    return base64.b64encode(content).decode('utf-8')


# Conversion to px
def convert_to_px(value, unit):
    value = float(value)
    if unit == 'px':
        return math.ceil(value)
    elif unit == 'pt':
        return math.ceil(value * 4 / 3)
    elif unit == 'in':
        return math.ceil(value * 96)
    elif unit == 'cm':
        return math.ceil(value * 96 / 2.54)
    elif unit == 'mm':
        return math.ceil(value * 96 / 2.54 * 10)
    elif unit == 'pc':
        return math.ceil(value * 16)
    else:
        return math.ceil(value) # Unknown unit, assume px