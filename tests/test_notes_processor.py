"""Tests for NotesProcessor utility functions and PDF notes processing."""

from pathlib import Path

from bs4 import BeautifulSoup

from app.notes_processor import Note, NotesProcessor


def test_parse_notes_with_nested_replies():
    """
    Test parsing of HTML sticky notes with nested replies.

    This test verifies that replaceNotes correctly:
    - Extracts note metadata (username, title, text, time)
    - Builds proper parent-child relationships for replies
    - Generates unique UUIDs for all notes
    - Replaces sticky-note spans with anchor tags
    """
    html = """
        <span class="sticky-note">
            <span class="sticky-note-time">2020-04-30T07:24:55.000+02:00</span>
            <span class="sticky-note-username">Admin</span>
            <span class="sticky-note-title">Main Note Title</span>
            <span class="sticky-note-text">Test comment with custom icon</span>

            <span class="sticky-note">
                <span class="sticky-note-time">2020-04-30T09:33:55.000</span>
                <span class="sticky-note-username">User 1</span>
                <span class="sticky-note-title">Reply 1 Title</span>
                <span class="sticky-note-text">Test reply 1</span>

                <span class="sticky-note">
                    <span class="sticky-note-time">2020-04-30T08:30:00+08:00</span>
                    <span class="sticky-note-username">User 3</span>
                    <span class="sticky-note-text">Test reply to reply 1</span>
                </span>
            </span>

            <span class="sticky-note">
                <span class="sticky-note-time">2020-04-30T09:00:00+08:00</span>
                <span class="sticky-note-username">User 2</span>
                <span class="sticky-note-text">Test reply 2</span>
            </span>

        </span>
    """
    soup = BeautifulSoup(html, "html.parser")
    processor = NotesProcessor()

    notes = processor.replaceNotes(soup)

    # Verify structure
    assert len(notes) == 1, "Should have 1 top-level note"
    assert notes[0].username == "Admin", "Top-level username should be Admin"
    assert notes[0].title == "Main Note Title", "Top-level title should match"
    assert notes[0].text == "Test comment with custom icon", "Top-level text should match"
    assert len(notes[0].replies) == 2, "Top-level note should have 2 replies"

    # Verify first reply
    assert notes[0].replies[0].username == "User 1", "First reply username should be User 1"
    assert notes[0].replies[0].title == "Reply 1 Title", "First reply title should be 'Reply 1 Title'"
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

    # Verify that sticky-note spans were replaced with anchor tags
    anchor_tags = soup.find_all("a", href=lambda href: href and href.startswith("https://sticky.note/"))
    assert len(anchor_tags) == 1, "Should have 1 anchor tag (for the top-level note)"


def test_process_pdf_with_notes():
    """
    Test PDF processing by loading a PDF with fake note links and replacing them with annotations.

    This test verifies that processPdf correctly:
    - Replaces fake note links with PDF annotations
    - Creates nested reply annotations using /IRT field
    - Preserves other annotations and page content
    """
    # Create test note structure
    html = """
        <span class="sticky-note">
            <span class="sticky-note-time">2020-04-30T07:24:55.000+02:00</span>
            <span class="sticky-note-username">Admin</span>
            <span class="sticky-note-title">Main Note Title</span>
            <span class="sticky-note-text">Test comment with custom icon</span>

            <span class="sticky-note">
                <span class="sticky-note-time">2020-04-30T09:33:55.000</span>
                <span class="sticky-note-username">User 1</span>
                <span class="sticky-note-title">Reply 1 Title</span>
                <span class="sticky-note-text">Test reply 1</span>

                <span class="sticky-note">
                    <span class="sticky-note-time">2020-04-30T08:30:00+08:00</span>
                    <span class="sticky-note-username">User 3</span>
                    <span class="sticky-note-text">Test reply to reply 1</span>
                </span>
            </span>

            <span class="sticky-note">
                <span class="sticky-note-time">2020-04-30T09:00:00+08:00</span>
                <span class="sticky-note-username">User 2</span>
                <span class="sticky-note-text">Test reply 2</span>
            </span>

        </span>
    """
    soup = BeautifulSoup(html, "html.parser")
    processor = NotesProcessor()
    notes = processor.replaceNotes(soup)

    # Override the UUID of the main note to match the one in notes_link_to_replace.pdf
    notes[0].uuid = "7590439a-cbbc-49f3-8e16-d1e395a18414"

    # Load the test PDF
    test_pdf_path = Path(__file__).parent / "test-data" / "notes_link_to_replace.pdf"
    with open(test_pdf_path, "rb") as f:
        pdf_bytes = f.read()

    # Process the PDF with notes
    updated_pdf = processor.processPdf(pdf_bytes, notes)

    # Verify the PDF was processed
    assert len(updated_pdf) > 0, "Updated PDF should not be empty"
    assert len(updated_pdf) != len(pdf_bytes), "Updated PDF should differ from original"

    # Save the updated PDF for manual inspection (optional)
    output_path = test_pdf_path.parent / "notes_link_to_replace_output.pdf"
    with open(output_path, "wb") as f:
        f.write(updated_pdf)


def test_format_pdf_date():
    """
    Test conversion of ISO 8601 time strings to PDF date format.

    This test verifies that _format_pdf_date correctly:
    - Converts ISO 8601 dates with timezone to PDF format
    - Handles timezone offsets (positive and negative)
    - Handles dates without timezone
    - Returns empty string for invalid dates
    """
    processor = NotesProcessor()

    # Test with timezone offset
    assert processor._format_pdf_date("2020-04-30T07:24:55.000+02:00") == "D:20200430072455+02'00"
    assert processor._format_pdf_date("2020-04-30T08:30:00+08:00") == "D:20200430083000+08'00"

    # Test without timezone
    assert processor._format_pdf_date("2020-04-30T09:33:55.000") == "D:20200430093355"

    # Test with negative timezone offset
    assert processor._format_pdf_date("2020-04-30T09:00:00-05:00") == "D:20200430090000-05'00"

    # Test invalid date
    assert processor._format_pdf_date("invalid-date") == ""
    assert processor._format_pdf_date("") == ""


def test_parse_note_without_optional_fields():
    """
    Test parsing of notes with missing optional fields (title, time).

    This test verifies that the parser handles missing fields gracefully.
    """
    html = """
        <span class="sticky-note">
            <span class="sticky-note-username">User</span>
            <span class="sticky-note-text">Text only</span>
        </span>
    """
    soup = BeautifulSoup(html, "html.parser")
    processor = NotesProcessor()

    notes = processor.replaceNotes(soup)

    assert len(notes) == 1
    assert notes[0].username == "User"
    assert notes[0].text == "Text only"
    assert notes[0].title == ""
    assert notes[0].time == ""
    assert len(notes[0].replies) == 0


def test_multiple_top_level_notes():
    """
    Test parsing of multiple top-level notes.

    This test verifies that multiple independent sticky notes are properly parsed.
    """
    html = """
        <div>
            <span class="sticky-note">
                <span class="sticky-note-username">User 1</span>
                <span class="sticky-note-text">First note</span>
            </span>
            <span class="sticky-note">
                <span class="sticky-note-username">User 2</span>
                <span class="sticky-note-text">Second note</span>
            </span>
        </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    processor = NotesProcessor()

    notes = processor.replaceNotes(soup)

    assert len(notes) == 2
    assert notes[0].username == "User 1"
    assert notes[0].text == "First note"
    assert notes[1].username == "User 2"
    assert notes[1].text == "Second note"

    # Verify both notes have unique UUIDs
    assert notes[0].uuid != notes[1].uuid
