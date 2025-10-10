"""
Notes (sticky notes) processing utilities for WeasyPrint service.

Features:
- Convert special <div class="weasyprint-note">...<div> with a special <a href="#note-id">...</a>
- Replaces links like "#note-id" with a native sticky notes
"""

import uuid
from dataclasses import dataclass, field
from io import BytesIO

from bs4 import BeautifulSoup, Tag
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Text


@dataclass
class Note:
    """Represents a single note with its content and nested replies."""

    username: str
    text: str
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
        # Extract username and text from direct children only
        username_tag = node.find("div", class_="weasyprint-note-username", recursive=False)
        text_tag = node.find("div", class_="weasyprint-note-text", recursive=False)

        username = username_tag.get_text(strip=True) if username_tag else ""
        text = text_tag.get_text(strip=True) if text_tag else ""

        # Find direct child notes (replies)
        replies: list[Note] = []
        for child in node.find_all(class_="weasyprint-note", recursive=False):
            if isinstance(child, Tag):
                reply = self._parse_note(child)
                replies.append(reply)

        return Note(username=username, text=text, replies=replies)

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

                                    # Build the note content with replies
                                    note_content = self._build_note_content(note)

                                    # Create text annotation (sticky note)
                                    text_annot = Text(
                                        rect=(float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])),
                                        text=note_content,
                                        open=False,
                                    )
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

    def _build_note_content(self, note: Note, level: int = 0) -> str:
        """Build formatted note content including all replies."""
        indent = "  " * level
        content = f"{indent}{note.username}: {note.text}"

        if note.replies:
            content += "\n"
            for reply in note.replies:
                content += "\n" + self._build_note_content(reply, level + 1)

        return content

    @staticmethod
    def test_init():
        html = """
            <div class="weasyprint-note">
                <div class="weasyprint-note-username">Admin</div>
                <div class="weasyprint-note-text">Test comment</div>

                <div class="weasyprint-note">
                    <div class="weasyprint-note-username">User 1</div>
                    <div class="weasyprint-note-text">Test reply 1</div>

                    <div class="weasyprint-note">
                        <div class="weasyprint-note-username">User 3</div>
                        <div class="weasyprint-note-text">Test reply to reply 1</div>
                    </div>
                </div>

                <div class="weasyprint-note">
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
        assert notes[0].text == "Test comment", "Top-level text should be 'Test comment'"
        assert len(notes[0].replies) == 2, "Top-level note should have 2 replies"

        # Verify first reply
        assert notes[0].replies[0].username == "User 1", "First reply username should be User 1"
        assert notes[0].replies[0].text == "Test reply 1", "First reply text should be 'Test reply 1'"
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
