"""
Notes (sticky notes) processing utilities for WeasyPrint service.

Features:
- Convert special <span class="sticky-note">...<span> with a special <a href="https://sticky.note/XXX">...</a>
- Replaces links above in the final PDF with a native sticky notes
- Supports custom PNG icons via appearance streams
"""

import uuid
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path

from bs4 import BeautifulSoup, Tag
from PIL import Image  # type: ignore[import-untyped]
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Text
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    RectangleObject,
    TextStringObject,
)


@dataclass
class Note:
    """Represents a single note with its content and nested replies."""

    time: str
    username: str
    text: str
    title: str = ""
    replies: list["Note"] = field(default_factory=list)
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))


class NotesProcessor:
    """Process SVG elements in HTML content."""

    def replaceNotes(self, parsed_html: BeautifulSoup) -> list[Note]:
        """Parse note trees from HTML and return structured Note objects."""
        notes: list[Note] = []
        for node in parsed_html.find_all(class_="sticky-note"):
            if isinstance(node, Tag) and node.find_parent(class_="sticky-note") is None:
                note = self._parse_note(node)
                notes.append(note)
                # Create a link that WeasyPrint will convert to annotation
                # Use an anchor with inline-block to reserve space without visible text
                fake_a_href: Tag = parsed_html.new_tag("a")
                fake_a_href.attrs["href"] = f"https://sticky.note/{note.uuid}"
                fake_a_href.attrs["style"] = "display: inline-block; width: 20px; height: 20px; text-decoration: none; color: transparent; background: transparent;"
                fake_a_href.string = " "  # Empty string
                node.replace_with(fake_a_href)

        return notes

    def _parse_note(self, node: Tag) -> Note:
        """Recursively parse a note node and its replies."""
        # Extract username, text, title, and time from direct children only
        time_tag = node.find("span", class_="sticky-note-time", recursive=False)
        username_tag = node.find("span", class_="sticky-note-username", recursive=False)
        text_tag = node.find("span", class_="sticky-note-text", recursive=False)
        title_tag = node.find("span", class_="sticky-note-title", recursive=False)

        time = time_tag.get_text(strip=True) if time_tag else ""
        username = username_tag.get_text(strip=True) if username_tag else ""
        text = text_tag.get_text(strip=True) if text_tag else ""
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Find direct child notes (replies)
        replies: list[Note] = []
        for child in node.find_all(class_="sticky-note", recursive=False):
            if isinstance(child, Tag):
                reply = self._parse_note(child)
                replies.append(reply)

        return Note(time=time, username=username, text=text, title=title, replies=replies)

    def processPdf(self, pdf_content: bytes, notes: list[Note]) -> bytes:
        """Process PDF to replace fake note links with actual PDF sticky note annotations with nested replies."""
        # Create a UUID to Note mapping for quick lookup (only top-level notes)
        note_map: dict[str, Note] = {note.uuid: note for note in notes}

        # Read the PDF
        reader = PdfReader(BytesIO(pdf_content))
        writer = PdfWriter()

        # Process each page
        for page in reader.pages:
            # Find and remove note links, create annotations instead
            notes_to_create: list[tuple[Note, tuple[float, float, float, float]]] = []

            if "/Annots" in page:
                annots_to_keep = []
                annots_array = page["/Annots"]  # type: ignore[index]
                # Type check: ensure annots_array is iterable
                if not isinstance(annots_array, list):
                    annots_array = list(annots_array) if hasattr(annots_array, "__iter__") else []  # type: ignore[assignment]
                for annot in annots_array:  # type: ignore[attr-defined]
                    annot_obj = annot.get_object()
                    # Check if this is a link annotation with our fake URL
                    if annot_obj.get("/Subtype") == "/Link" and "/A" in annot_obj:
                        action = annot_obj["/A"]
                        if "/URI" in action:
                            uri = str(action["/URI"])
                            if uri.startswith("https://sticky.note/"):
                                # Extract UUID from URI
                                note_uuid = uri.replace("https://sticky.note/", "")
                                if note_uuid in note_map:
                                    # Store note and rect for later processing
                                    note = note_map[note_uuid]
                                    rect = annot_obj["/Rect"]
                                    rect_tuple = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
                                    notes_to_create.append((note, rect_tuple))
                                    # Skip adding this link annotation
                                    continue

                    # Keep other annotations
                    annots_to_keep.append(annot)

                # Update annotations list with kept annotations
                if annots_to_keep:
                    page[NameObject("/Annots")] = ArrayObject(annots_to_keep)
                else:
                    del page["/Annots"]

            # Add page to writer
            writer.add_page(page)
            page_number = len(writer.pages) - 1

            # Now create annotations with proper parent-child relationships
            for note, rect in notes_to_create:
                self._create_note_annotation_with_replies(writer, page_number, note, rect, parent_ref=None)

        # Write to bytes
        output = BytesIO()
        writer.write(output)
        return output.getvalue()

    def _embed_png_as_xobject(self, writer: PdfWriter, png_path: str) -> object | None:
        """
        Embed a PNG image as an XObject in the PDF.

        Args:
            writer: PdfWriter instance
            png_path: Path to the PNG file

        Returns:
            XObject dictionary or None if the image cannot be loaded
        """
        try:
            # Load and process the PNG image
            img = Image.open(png_path)  # type: ignore[assignment]

            # Convert to RGB if necessary (PDF XObjects require RGB or L)
            if img.mode == "RGBA":
                # Convert RGBA to RGB by compositing over white background
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3] if len(img.split()) == 4 else None)  # 3 is the alpha channel
                img = background  # type: ignore[assignment]
            elif img.mode not in ("RGB", "L"):
                img = img.convert("RGB")  # type: ignore[assignment]

            # Get image dimensions
            width, height = img.size

            # Get raw image data (uncompressed RGB bytes)
            img_data = img.tobytes()

            # Compress the raw image data
            compressed_data = zlib.compress(img_data)

            # Create the XObject dictionary
            xobject = DecodedStreamObject()
            xobject[NameObject("/Type")] = NameObject("/XObject")
            xobject[NameObject("/Subtype")] = NameObject("/Image")
            xobject[NameObject("/Width")] = NumberObject(width)
            xobject[NameObject("/Height")] = NumberObject(height)
            xobject[NameObject("/ColorSpace")] = NameObject("/DeviceRGB" if img.mode == "RGB" else "/DeviceGray")
            xobject[NameObject("/BitsPerComponent")] = NumberObject(8)
            xobject[NameObject("/Filter")] = NameObject("/FlateDecode")
            xobject.set_data(compressed_data)

            # Add the XObject to the PDF writer
            return writer._add_object(xobject)

        except Exception as e:
            print(f"Warning: Failed to embed PNG icon from {png_path}: {e}")
            return None

    def _create_custom_appearance(
        self, writer: PdfWriter, rect: tuple[float, float, float, float], xobject_ref: object
    ) -> DictionaryObject:
        """
        Create a custom appearance stream for an annotation using an embedded image.

        Args:
            writer: PdfWriter instance
            rect: Rectangle coordinates (x1, y1, x2, y2) for the annotation
            xobject_ref: Reference to the embedded XObject (image)

        Returns:
            Appearance dictionary (/AP) with Normal appearance stream
        """
        # Calculate annotation dimensions
        x1, y1, x2, y2 = rect
        width = x2 - x1
        height = y2 - y1

        # Create the appearance stream content (PDF content stream)
        # PDF uses bottom-left origin, but images are top-left origin
        # We need to flip the image vertically: scale Y by -1 and translate
        # Transformation matrix: [width 0 0 -height 0 height]
        # This scales to width/height and flips Y axis
        content = f"q {width} 0 0 {-height} 0 {height} cm /Img Do Q"

        # Create the appearance stream
        appearance_stream = DecodedStreamObject()
        appearance_stream[NameObject("/Type")] = NameObject("/XObject")
        appearance_stream[NameObject("/Subtype")] = NameObject("/Form")
        appearance_stream[NameObject("/BBox")] = ArrayObject([NumberObject(0), NumberObject(0), NumberObject(width), NumberObject(height)])
        appearance_stream[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/XObject"): DictionaryObject({NameObject("/Img"): xobject_ref})}
        )
        appearance_stream.set_data(content.encode("latin-1"))

        # Add the appearance stream to the PDF
        appearance_ref = writer._add_object(appearance_stream)

        # Create the appearance dictionary
        appearance_dict = DictionaryObject()
        appearance_dict[NameObject("/N")] = appearance_ref  # /N = Normal appearance

        return appearance_dict

    def _create_note_annotation_with_replies(
        self, writer: PdfWriter, page_number: int, note: Note, rect: tuple[float, float, float, float], parent_ref: object | None = None
    ) -> object:
        """
        Recursively create note annotations with proper parent-child relationships using /IRT field.

        Args:
            writer: PdfWriter instance
            page_number: Page number to add annotation to
            note: Note object to create annotation from
            rect: Rectangle coordinates (x1, y1, x2, y2) for the annotation
            parent_ref: Reference to parent annotation (for replies) or None for top-level notes

        Returns:
            Reference to the created annotation (for use as parent in child annotations)
        """
        # Create text annotation (sticky note) with proper PDF fields
        text_annot = Text(
            rect=rect,
            text=note.text,
            open=False,
        )

        # Manually set PDF annotation fields using proper PDF objects
        # /T = Author/username
        # /Subj = Subject/title
        # /AP = Custom appearance (icon)
        # /CreationDate = Creation date in PDF format
        # /M = Modification date in PDF format
        annot_dict = text_annot
        annot_dict[NameObject("/T")] = TextStringObject(note.username)

        # Always use custom icon from static folder
        custom_icon_path = str(Path(__file__).parent / "static" / "note.png")
        if Path(custom_icon_path).exists():
            xobject_ref = self._embed_png_as_xobject(writer, custom_icon_path)
            if xobject_ref is not None:
                appearance_dict = self._create_custom_appearance(writer, rect, xobject_ref)
                annot_dict[NameObject("/AP")] = appearance_dict

        # Only set date fields if we have a valid date
        if note.time:
            pdf_date = self._format_pdf_date(note.time)
            # Only set if we got a valid PDF date (starts with "D:")
            if pdf_date and pdf_date.startswith("D:"):
                annot_dict[NameObject("/CreationDate")] = TextStringObject(pdf_date)
                annot_dict[NameObject("/M")] = TextStringObject(pdf_date)

        if note.title:
            annot_dict[NameObject("/Subj")] = TextStringObject(note.title)

        # If this is a reply, set the /IRT (In Reply To) field
        if parent_ref is not None:
            annot_dict[NameObject("/IRT")] = parent_ref
            # /RT specifies reply type: /R = Reply (default)
            annot_dict[NameObject("/RT")] = NameObject("/R")

        # Add annotation to the page
        writer.add_annotation(page_number, text_annot)

        # Get reference to the annotation we just added
        # The annotation is now in the page's annotation array
        page = writer.pages[page_number]
        if "/Annots" in page:
            # The last annotation in the list is the one we just added
            annots = page["/Annots"]
            if isinstance(annots, list) and len(annots) > 0:
                current_annot_ref = annots[-1]
            else:
                return None
        else:
            # This shouldn't happen, but handle gracefully
            return None

        # Recursively create reply annotations
        for reply in note.replies:
            # Replies use the same rect as parent (they appear as nested in the UI)
            self._create_note_annotation_with_replies(writer, page_number, reply, rect, current_annot_ref)

        return current_annot_ref

    def _format_pdf_date(self, time_str: str) -> str:
        """
        Convert ISO 8601 time string to PDF date format.
        PDF date format: D:YYYYMMDDHHmmSSOHH'mm
        Example: D:20251008112400+02'00

        Args:
            time_str: ISO 8601 time string (e.g., "2020-04-30T08:00:00.000+08:00")

        Returns:
            PDF formatted date string with timezone
        """
        try:
            # Parse ISO 8601 format with timezone support
            # Python 3.11+ supports fromisoformat with most ISO 8601 variants
            dt = datetime.fromisoformat(time_str)

            # Build PDF date format: D:YYYYMMDDHHmmSSOHH'mm
            base_date = dt.strftime('%Y%m%d%H%M%S')

            # Extract timezone offset
            if dt.tzinfo is not None:
                # Get UTC offset in seconds
                offset = dt.utcoffset()
                if offset is not None:
                    total_seconds = int(offset.total_seconds())
                    hours = total_seconds // 3600
                    minutes = abs(total_seconds % 3600) // 60

                    # Format as +HH'mm or -HH'mm
                    tz_str = f"{hours:+03d}'{minutes:02d}"
                    return f"D:{base_date}{tz_str}"

            # No timezone info, return without TZ
            return f"D:{base_date}"

        except (ValueError, AttributeError):
            # If ISO format parsing fails, return empty to skip setting the field
            return ""
