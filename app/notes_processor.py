"""
Notes (sticky notes) processing utilities for WeasyPrint service.

Features:
- Convert special <div class="weasyprint-note">...<div> with a special <a href="#note-id">...</a>
- Replaces links like "#note-id" with a native sticky notes
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
    icon: str = "Comment"
    custom_icon_path: str = ""  # Path to custom PNG icon file
    replies: list["Note"] = field(default_factory=list)
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))


class NotesProcessor:
    """Process SVG elements in HTML content."""

    def replaceNotes(self, parsed_html: BeautifulSoup) -> list[Note]:
        """Parse note trees from HTML and return structured Note objects."""
        notes: list[Note] = []
        for node in parsed_html.find_all(class_="weasyprint-note"):
            if isinstance(node, Tag) and node.find_parent(class_="weasyprint-note") is None:
                note = self._parse_note(node)
                notes.append(note)
                # Create a link that WeasyPrint will convert to annotation
                # Use a span with background to reserve space without text
                fake_a_href: Tag = parsed_html.new_tag("a")
                fake_a_href.attrs["href"] = f"https://weasyprint.note/{note.uuid}"
                fake_a_href.attrs["style"] = "display: inline-block; width: 20px; height: 20px; text-decoration: none; color: transparent; background: transparent;"
                fake_a_href.string = " "  # Empty string
                node.replace_with(fake_a_href)

        return notes

    def _parse_note(self, node: Tag) -> Note:
        """Recursively parse a note node and its replies."""
        # Extract username, text, title, icon, custom_icon_path, and time from direct children only
        time_tag = node.find("div", class_="weasyprint-note-time", recursive=False)
        username_tag = node.find("div", class_="weasyprint-note-username", recursive=False)
        text_tag = node.find("div", class_="weasyprint-note-text", recursive=False)
        title_tag = node.find("div", class_="weasyprint-note-title", recursive=False)
        icon_tag = node.find("div", class_="weasyprint-note-icon", recursive=False)
        custom_icon_tag = node.find("div", class_="weasyprint-note-custom-icon", recursive=False)

        time = time_tag.get_text(strip=True) if time_tag else ""
        username = username_tag.get_text(strip=True) if username_tag else ""
        text = text_tag.get_text(strip=True) if text_tag else ""
        title = title_tag.get_text(strip=True) if title_tag else ""
        icon = icon_tag.get_text(strip=True) if icon_tag else "Comment"
        custom_icon_path = custom_icon_tag.get_text(strip=True) if custom_icon_tag else ""

        # Find direct child notes (replies)
        replies: list[Note] = []
        for child in node.find_all(class_="weasyprint-note", recursive=False):
            if isinstance(child, Tag):
                reply = self._parse_note(child)
                replies.append(reply)

        return Note(time=time, username=username, text=text, title=title, icon=icon, custom_icon_path=custom_icon_path, replies=replies)

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
                            if uri.startswith("https://weasyprint.note/"):
                                # Extract UUID from URI
                                note_uuid = uri.replace("https://weasyprint.note/", "")
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
                    page["/Annots"] = annots_to_keep
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
        # /Name = Icon name (Comment, Key, Note, Help, NewParagraph, Paragraph, Insert)
        # /CreationDate = Creation date in PDF format
        # /M = Modification date in PDF format
        annot_dict = text_annot
        annot_dict[NameObject("/T")] = TextStringObject(note.username)

        # Set icon if specified (defaults to "Comment")
        if note.icon:
            annot_dict[NameObject("/Name")] = NameObject(f"/{note.icon}")

        # If custom icon is specified, create custom appearance
        if note.custom_icon_path and Path(note.custom_icon_path).exists():
            xobject_ref = self._embed_png_as_xobject(writer, note.custom_icon_path)
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

# Comment, Key, Note, Help, NewParagraph, Paragraph, Insert
    @staticmethod
    def test_parse() -> list[Note]:
        # Get path to custom icon for testing
        from pathlib import Path
        custom_icon_path = str(Path(__file__).parent.parent / "tests" / "test-data" / "note.png")

        html = f"""
            <div class="weasyprint-note">
                <div class="weasyprint-note-time">2020-04-30T07:24:55.000+02:00</div>
                <div class="weasyprint-note-username">Admin</div>
                <div class="weasyprint-note-title">Main Note Title (Custom Icon)</div>
                <div class="weasyprint-note-custom-icon">{custom_icon_path}</div>
                <div class="weasyprint-note-text">Test comment with custom icon</div>

                <div class="weasyprint-note">
                    <div class="weasyprint-note-time">2020-04-30T09:33:55.000</div>
                    <div class="weasyprint-note-username">User 1</div>
                    <div class="weasyprint-note-title">Reply 1 Title</div>
                    <div class="weasyprint-note-icon">Help</div>
                    <div class="weasyprint-note-text">Test reply 1</div>

                    <div class="weasyprint-note">
                        <div class="weasyprint-note-time">2020-04-30T08:30:00+08:00</div>
                        <div class="weasyprint-note-username">User 3</div>
                        <div class="weasyprint-note-text">Test reply to reply 1</div>
                    </div>
                </div>

                <div class="weasyprint-note">
                    <div class="weasyprint-note-time">2020-04-30T09:00:00+08:00</div>
                    <div class="weasyprint-note-username">User 2</div>
                    <div class="weasyprint-note-icon">Note</div>
                    <div class="weasyprint-note-text">Test reply 2</div>
                </div>

            </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        processor = NotesProcessor()

        notes = processor.replaceNotes(soup)

        # Override the UUID of the main note to match the one in date7.pdf
        notes[0].uuid = "7590439a-cbbc-49f3-8e16-d1e395a18414"

        # Verify structure
        assert len(notes) == 1, "Should have 1 top-level note"
        assert notes[0].username == "Admin", "Top-level username should be Admin"
        assert notes[0].title == "Main Note Title (Custom Icon)", "Top-level title should match"
        assert notes[0].custom_icon_path == custom_icon_path, f"Top-level custom_icon_path should be '{custom_icon_path}'"
        assert notes[0].text == "Test comment with custom icon", "Top-level text should match"
        # assert notes[0].time == "2020-04-30T08:00:00.000+08:00", "Top-level time should be ISO 8601 format"
        assert len(notes[0].replies) == 2, "Top-level note should have 2 replies"

        # Verify first reply
        assert notes[0].replies[0].username == "User 1", "First reply username should be User 1"
        assert notes[0].replies[0].title == "Reply 1 Title", "First reply title should be 'Reply 1 Title'"
        # assert notes[0].replies[0].icon == "Help", "First reply icon should be 'Help'"
        assert notes[0].replies[0].text == "Test reply 1", "First reply text should be 'Test reply 1'"
        # assert notes[0].replies[0].time == "2020-04-30T08:15:00+08:00", "First reply time should be ISO 8601 format"
        assert len(notes[0].replies[0].replies) == 1, "First reply should have 1 nested reply"

        # Verify nested reply (no icon specified, should default to "Comment")
        assert notes[0].replies[0].replies[0].username == "User 3", "Nested reply username should be User 3"
        # assert notes[0].replies[0].replies[0].icon == "Comment", "Nested reply icon should default to 'Comment'"
        assert notes[0].replies[0].replies[0].text == "Test reply to reply 1", "Nested reply text should match"

        # Verify second reply
        assert notes[0].replies[1].username == "User 2", "Second reply username should be User 2"
        # assert notes[0].replies[1].icon == "Note", "Second reply icon should be 'Note'"
        assert notes[0].replies[1].text == "Test reply 2", "Second reply text should be 'Test reply 2'"
        assert len(notes[0].replies[1].replies) == 0, "Second reply should have no nested replies"

        # Verify UUIDs are generated and unique
        all_uuids = set()

        def collect_uuids(note: Note) -> None:
            all_uuids.add(note.uuid)
            for reply in note.replies:
                collect_uuids(reply)

        for note in notes:
            collect_uuids(note)

        assert len(all_uuids) == 4, "Should have 4 unique UUIDs (1 parent + 3 replies)"

        # Verify UUID format (basic check for UUID4 format)
        import re

        uuid_pattern = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE)
        for uid in all_uuids:
            assert uuid_pattern.match(uid), f"UUID {uid} is not a valid UUID4 format"

        print("All assertions passed!")

        return notes

    @staticmethod
    def test_replace(notes: list[Note]) -> None:
        """Test PDF processing by loading a PDF with fake note links and replacing them with annotations."""
        from pathlib import Path

        # Load the test PDF
        test_pdf_path = Path(__file__).parent.parent / "tests" / "test-data" / "date7.pdf"
        with open(test_pdf_path, "rb") as f:
            pdf_bytes = f.read()

        print(f"Loaded PDF from {test_pdf_path} ({len(pdf_bytes)} bytes)")

        # Process the PDF with notes
        processor = NotesProcessor()
        updated_pdf = processor.processPdf(pdf_bytes, notes)

        # Save the updated PDF
        output_path = test_pdf_path.parent / "date7_output.pdf"
        with open(output_path, "wb") as f:
            f.write(updated_pdf)

        print(f"Saved updated PDF to {output_path} ({len(updated_pdf)} bytes)")
        print(f"Added {len(notes)} note(s) with nested replies")

if __name__ == "__main__":
    notes = NotesProcessor.test_parse()
    NotesProcessor.test_replace(notes)
