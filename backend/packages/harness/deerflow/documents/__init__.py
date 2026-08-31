"""Long-document handling: page anchors, extraction quality, chunking, OCR.

The pieces here exist so a document larger than the model's context window is
read in bounded pieces rather than all at once, and so a PDF whose text layer is
empty is *reported* as such instead of being summarised into fiction.
"""
