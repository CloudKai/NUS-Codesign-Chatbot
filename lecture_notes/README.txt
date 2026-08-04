Course materials folder
=======================

Place instructor-managed materials in these folders, then refresh Co-design Chatbot:

- lectureNotes/  -> shown under "Lecture Notes"
- readings/      -> shown under "Readings"

Files at the folder root default to "Lecture Notes" unless "reading" appears
in the filename. The app treats synchronized course materials as read-only:
students can select and view them, but cannot download or delete them in the UI.

Supported formats:
- PDF (.pdf)
- Word (.docx)
- PowerPoint (.pptx)
- Excel (.xlsx)
- Text, Markdown, CSV, JSON, and common code files
- PNG, JPEG, WebP, and GIF images

Instructor-managed course files may be up to 50 MB. Student uploads keep their
separate 10 MB limit. Prefer compressed PDFs so new notebooks import faster.

The Sources panel automatically copies supported files into the active notebook,
selects them, and includes extracted text in grounded responses. Originals stay
in their current folders and are never moved. This README file is never imported.
