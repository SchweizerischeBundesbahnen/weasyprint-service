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
    pattern = re.compile(r'<img(?P<intermediate>[^>]+?src="data:)(?P<type>[^;>]*?);base64, (?P<base64>[^">]*?)"')
    return re.sub(pattern, replace_img_base64, html)


def get_svg_content(content_type, content_base64):
    # We do not require to have 'image/svg+xml' content type coz not all systems will properly set it

    if content_type in NON_SVG_CONTENT_TYPES:
        return False  # Skip processing if content type set explicitly as not svg

    decoded_content = base64.b64decode(content_base64)
    if b'\0' in decoded_content:
        return False  # Skip processing if decoded content is binary (not text)

    svg_content = decoded_content.decode('utf-8')

    # Fast check that this is a svg
    if '</svg>' not in svg_content:
        return False

    return svg_content


def replace_img_base64(match):
    entry = match.group(0)
    content_type = match.group('type')
    content_base64 = match.group('base64')

    svg_content = get_svg_content(content_type, content_base64)
    if svg_content is False:
        return entry
    else:
        replaced_content_base64 = replace_svg_with_png(svg_content)
        if replaced_content_base64 == content_base64:
            return entry  # For some reason content wasn't replaced
        else:
            return f'<img{match.group("intermediate")}image/svg+xml;base64, {replaced_content_base64}"'


# Checks that base64 encoded content is a svg image and replaces it with the png screenshot made by chromium
def replace_svg_with_png(svg_content):
    chromium_executable = os.environ.get('CHROMIUM_EXECUTABLE_PATH')
    if not chromium_executable:
        logging.error('CHROMIUM_EXECUTABLE_PATH not set')
        return svg_content

    # Fetch width & height from root svg tag
    match = re.search(r'<svg[^>]+?width="(?P<width>[\d.]+)', svg_content)
    if match:
        width = match.group('width')
    else:
        logging.error('Cannot find svg width in ' + svg_content)
        return svg_content

    match = re.search(r'<svg[^>]+?height="(?P<height>[\d.]+)', svg_content)
    if match:
        height = match.group('height')
    else:
        logging.error('Cannot find svg height in ' + svg_content)
        return svg_content

    # Log large svg content size
    svg_content_length = len(svg_content)
    if svg_content_length > 100_000:
        logging.warning(f"SVG content length: {svg_content_length}")

    # Will be used as a name for tmp files
    uuid = str(uuid4())

    temp_folder = tempfile.gettempdir()

    # Put svg into tmp file
    svg_filepath = os.path.join(temp_folder, uuid + '.svg')
    f = open(svg_filepath, 'w', encoding='utf-8')
    f.write(svg_content)
    f.close()

    # Feed svg file to chromium
    png_filepath = os.path.join(temp_folder, uuid + '.png')

    chromium_command = create_chromium_command(
        chromium_executable,
        height,
        width,
        png_filepath,
        svg_filepath,
    )

    result = subprocess.run(chromium_command)

    # Remove tmp svg file
    os.remove(svg_filepath)

    if result.returncode != 0:
        logging.error(f'Error converting to png, returncode = {result.returncode}')
        return svg_content

    # Get resulting screenshot content
    with open(png_filepath, 'rb') as img_file:
        img_data = img_file.read()
        png_base64 = base64.b64encode(img_data).decode('utf-8')

    # Remove tmp png file
    os.remove(png_filepath)

    return png_base64


def create_chromium_command(chromium_executable, height, width, png_filepath, svg_filepath):
    # Check if the ENABLE_HARDWARE_ACCELERATION environment variable is set to true
    enable_hardware_acceleration = os.getenv('ENABLE_HARDWARE_ACCELERATION', 'false').lower() == 'true'

    command = [
        f'{chromium_executable}',
    ]

    if not enable_hardware_acceleration:
        command.extend([
            '--disable-gpu',
            '--disable-software-rasterizer',
            '--disable-dev-shm-usage',
        ])

    command.extend([
        '--headless=old',  # because of issue in new with SVG conversion
        '--no-sandbox',
        '--default-background-color=00000000',
        '--hide-scrollbars',
        '--enable-features=ConversionMeasurement,AttributionReportingCrossAppWeb',
        f'--screenshot={png_filepath}',
        f'--window-size={width},{height}',
        f'{svg_filepath}',
    ])

    return command
