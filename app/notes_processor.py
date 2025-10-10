"""
Notes (sticky notes) processing utilities for WeasyPrint service.

Features:
- Convert special <div class="weasyprint-note">...<div> with a special <a href="#note-id">...</a>
- Replaces links like "#note-id" with a native sticky notes
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO

from bs4 import BeautifulSoup, Tag
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Text
from pypdf.generic import NameObject, TextStringObject


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
        for node in parsed_html.find_all(class_="weasyprint-note"):
            if isinstance(node, Tag) and node.find_parent(class_="weasyprint-note") is None:
                note = self._parse_note(node)
                notes.append(note)
                fake_a_href: Tag = parsed_html.new_tag("a")
                fake_a_href.attrs["href"] = f"https://weasyprint.note/{note.uuid}"
                fake_a_href.attrs["style"] = "display: inline-block; width: 20px; height: 20px; overflow: hidden;"
                fake_a_href.string = "N"
                node.replace_with(fake_a_href)

        return notes

    def _parse_note(self, node: Tag) -> Note:
        """Recursively parse a note node and its replies."""
        # Extract username, text, title, and time from direct children only
        time_tag = node.find("div", class_="weasyprint-note-time", recursive=False)
        username_tag = node.find("div", class_="weasyprint-note-username", recursive=False)
        text_tag = node.find("div", class_="weasyprint-note-text", recursive=False)
        title_tag = node.find("div", class_="weasyprint-note-title", recursive=False)

        time = time_tag.get_text(strip=True) if time_tag else ""
        username = username_tag.get_text(strip=True) if username_tag else ""
        text = text_tag.get_text(strip=True) if text_tag else ""
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Find direct child notes (replies)
        replies: list[Note] = []
        for child in node.find_all(class_="weasyprint-note", recursive=False):
            if isinstance(child, Tag):
                reply = self._parse_note(child)
                replies.append(reply)

        return Note(time=time, username=username, text=text, title=title, replies=replies)

    def processPdf(self, pdf_content: bytes, notes: list[Note]) -> bytes:
        """Process PDF to replace fake note links with actual PDF sticky note annotations."""
        # Create a UUID to Note mapping for quick lookup (only top-level notes)
        note_map: dict[str, Note] = {note.uuid: note for note in notes}

        # Read the PDF
        reader = PdfReader(BytesIO(pdf_content))
        writer = PdfWriter()

        # Process each page
        for page in reader.pages:
            # Find and remove note links, create annotations instead
            new_annotations = []

            if "/Annots" in page:
                annots_to_keep = []
                for annot in page["/Annots"]:
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
                                    # Get the note and create a sticky note annotation
                                    note = note_map[note_uuid]
                                    rect = annot_obj["/Rect"]

                                    # Build the note content (main note text + replies)
                                    main_content = f"{note.text}"
                                    replies_content = self._build_note_content_for_replies(note)
                                    full_content = f"{main_content}\n\n{replies_content}" if replies_content else main_content

                                    # Create text annotation (sticky note) with proper PDF fields
                                    text_annot = Text(
                                        rect=(float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])),
                                        text=full_content,
                                        open=False,
                                    )

                                    # Manually set PDF annotation fields using proper PDF objects
                                    # /T = Author/username
                                    # /Subj = Subject/title
                                    # /CreationDate = Creation date in PDF format
                                    # /M = Modification date in PDF format
                                    annot_dict = text_annot
                                    annot_dict[NameObject("/T")] = TextStringObject(note.username)

                                    pdf_date = self._format_pdf_date(note.time)
                                    annot_dict[NameObject("/CreationDate")] = TextStringObject(pdf_date)
                                    annot_dict[NameObject("/M")] = TextStringObject(pdf_date)

                                    if note.title:
                                        annot_dict[NameObject("/Subj")] = TextStringObject(note.title)

                                    new_annotations.append(text_annot)
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

            # Add new text annotations to the page in the writer
            page_number = len(writer.pages) - 1
            for text_annot in new_annotations:
                writer.add_annotation(page_number, text_annot)

        # Write to bytes
        output = BytesIO()
        writer.write(output)
        return output.getvalue()

    def _format_pdf_date(self, time_str: str) -> str:
        """
        Convert time string to PDF date format.
        PDF date format: D:YYYYMMDDHHmmSSOHH'mm
        Example: D:20251008112400+02'00

        Args:
            time_str: Time string (e.g., "2025-10-08 11:24")

        Returns:
            PDF formatted date string
        """
        try:
            # Try to parse common formats
            for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]:
                try:
                    dt = datetime.strptime(time_str, fmt)
                    # PDF date format: D:YYYYMMDDHHmmSS
                    return f"D:{dt.strftime('%Y%m%d%H%M%S')}"
                except ValueError:
                    continue
            # If parsing fails, return original string
            return time_str
        except Exception:
            return time_str

    def _build_note_content(self, note: Note, level: int = 0) -> str:
        """Build formatted note content including all replies."""
        indent = "  " * level
        content = f"{indent}{note.username}: {note.text}"

        if note.replies:
            content += "\n"
            for reply in note.replies:
                content += "\n" + self._build_note_content(reply, level + 1)

        return content

    def _build_note_content_for_replies(self, note: Note) -> str:
        """Build formatted content for replies only (excluding the top-level note)."""
        if not note.replies:
            return ""

        content_parts = []
        for reply in note.replies:
            content_parts.append(self._build_note_content(reply, level=0))

        return "\n\n".join(content_parts)

    @staticmethod
    def test_init():
        html = """
            <div class="weasyprint-note">
                <div class="weasyprint-note-time">2025-10-08 11:24</div>
                <div class="weasyprint-note-username">Admin</div>
                <div class="weasyprint-note-title">Main Note Title</div>
                <div class="weasyprint-note-text">Test comment</div>

                <div class="weasyprint-note">
                    <div class="weasyprint-note-time">2025-10-08 11:25</div>
                    <div class="weasyprint-note-username">User 1</div>
                    <div class="weasyprint-note-title">Reply 1 Title</div>
                    <div class="weasyprint-note-text">Test reply 1</div>

                    <div class="weasyprint-note">
                        <div class="weasyprint-note-time">2025-10-08 11:27</div>
                        <div class="weasyprint-note-username">User 3</div>
                        <div class="weasyprint-note-text">Test reply to reply 1</div>
                    </div>
                </div>

                <div class="weasyprint-note">
                    <div class="weasyprint-note-time">2025-10-08 12:24</div>
                    <div class="weasyprint-note-username">User 2</div>
                    <div class="weasyprint-note-text">Test reply 2</div>
                </div>

            </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        processor = NotesProcessor()

        notes = processor.replaceNotes(soup)

        # Verify structure
        assert len(notes) == 1, "Should have 1 top-level note"
        assert notes[0].username == "Admin", "Top-level username should be Admin"
        assert notes[0].title == "Main Note Title", "Top-level title should be 'Main Note Title'"
        assert notes[0].text == "Test comment", "Top-level text should be 'Test comment'"
        assert notes[0].time == "2025-10-08 11:24", "Top-level time should be '2025-10-08 11:24'"
        assert len(notes[0].replies) == 2, "Top-level note should have 2 replies"

        # Verify first reply
        assert notes[0].replies[0].username == "User 1", "First reply username should be User 1"
        assert notes[0].replies[0].title == "Reply 1 Title", "First reply title should be 'Reply 1 Title'"
        assert notes[0].replies[0].text == "Test reply 1", "First reply text should be 'Test reply 1'"
        assert notes[0].replies[0].time == "2025-10-08 11:25", "First reply time should be '2025-10-08 11:25'"
        assert len(notes[0].replies[0].replies) == 1, "First reply should have 1 nested reply"

        # Verify nested reply
        assert notes[0].replies[0].replies[0].username == "User 3", "Nested reply username should be User 3"
        assert notes[0].replies[0].replies[0].text == "Test reply to reply 1", "Nested reply text should match"

        # Verify second reply
        assert notes[0].replies[1].username == "User 2", "Second reply username should be User 2"
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


if __name__ == "__main__":
    NotesProcessor.test_init()
