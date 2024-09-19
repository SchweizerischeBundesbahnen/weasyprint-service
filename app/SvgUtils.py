import base64
import logging
import os
import re
import subprocess
import tempfile
from uuid import uuid4

NON_SVG_CONTENT_TYPES = ('image/jpeg', 'image/png', 'image/gif')


# Process img tags, replacing base64 SVG images with PNGs
def process_svg(html):
    pattern = re.compile(r'<img(?P<intermediate>[^>]+?src="data:)(?P<type>[^;>]*?);base64,\s?(?P<base64>[^">]*?)"')
    return re.sub(pattern, replace_img_base64, html)


# Decode and validate if the provided content is SVG.
def get_svg_content(content_type, content_base64):
    # We do not require to have 'image/svg+xml' content type coz not all systems will properly set it

    if content_type in NON_SVG_CONTENT_TYPES:
        return False  # Skip processing if content type set explicitly as not svg

    try:
        decoded_content = base64.b64decode(content_base64)
        if b'\0' in decoded_content:
            return False  # Skip processing if decoded content is binary (not text)

        svg_content = decoded_content.decode('utf-8')

        # Fast check that this is a svg
        if '</svg>' not in svg_content:
            return False

        return svg_content
    except Exception as e:
        logging.error(f"Failed to decode base64 content: {e}")
        return False


# Replace base64 SVG images with PNG equivalents in the HTML img tag.
def replace_img_base64(match):
    entry = match.group(0)
    content_type = match.group('type')
    content_base64 = match.group('base64')

    svg_content = get_svg_content(content_type, content_base64)
    if svg_content is False:
        return entry

    replaced_content_base64 = replace_svg_with_png(svg_content)
    if replaced_content_base64 == content_base64:
        return entry  # For some reason content wasn't replaced

    return f'<img{match.group("intermediate")}image/svg+xml;base64,{replaced_content_base64}"'


# Checks that base64 encoded content is a svg image and replaces it with the png screenshot made by chromium
def replace_svg_with_png(svg_content):
    width, height = extract_svg_dimensions(svg_content)
    if not width or not height:
        return svg_content

    svg_filepath, png_filepath = prepare_temp_files(svg_content)
    if not svg_filepath or not png_filepath:
        return svg_content

    if not convert_svg_to_png(width, height, png_filepath, svg_filepath):
        return svg_content

    png_base64 = read_and_cleanup_png(png_filepath)
    return png_base64 if png_base64 else svg_content


# Extract the width and height from the SVG tag
def extract_svg_dimensions(svg_content):
    width_match = re.search(r'<svg[^>]+?width="(?P<width>[\d.]+)', svg_content)
    height_match = re.search(r'<svg[^>]+?height="(?P<height>[\d.]+)', svg_content)

    width = width_match.group('width') if width_match else None
    height = height_match.group('height') if height_match else None

    if not width or not height:
        logging.error(f"Cannot find SVG dimensions. Width: {width}, Height: {height}")
    return width, height


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
    result = subprocess.run(command)

    if result.returncode != 0:
        logging.error(f"Error converting SVG to PNG, return code = {result.returncode}")
        return False

    return True


# Read the PNG file, encode it in base64, and clean up the temporary file.
def read_and_cleanup_png(png_filepath):
    try:
        with open(png_filepath, 'rb') as img_file:
            img_data = img_file.read()

        png_base64 = base64.b64encode(img_data).decode('utf-8')
        os.remove(png_filepath)
        return png_base64
    except Exception as e:
        logging.error(f"Failed to read or clean up PNG file: {e}")
        return None


# Create the Chromium command for converting SVG to PNG
def create_chromium_command(width, height, png_filepath, svg_filepath):
    chromium_executable = os.environ.get('CHROMIUM_EXECUTABLE_PATH')
    if not chromium_executable:
        logging.error('CHROMIUM_EXECUTABLE_PATH is not set.')
        return None

    enable_hardware_acceleration = os.getenv('ENABLE_HARDWARE_ACCELERATION', 'false').lower() == 'true'

    command = [
        chromium_executable,
        '--headless=old',
        '--no-sandbox',
        '--default-background-color=00000000',
        '--hide-scrollbars',
        '--enable-features=ConversionMeasurement,AttributionReportingCrossAppWeb',
        f'--screenshot={png_filepath}',
        f'--window-size={width},{height}',
        svg_filepath,
    ]

    if not enable_hardware_acceleration:
        command.extend([
            '--disable-gpu',
            '--disable-software-rasterizer',
            '--disable-dev-shm-usage',
        ])

    return command
