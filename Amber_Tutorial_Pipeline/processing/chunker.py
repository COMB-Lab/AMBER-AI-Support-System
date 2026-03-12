def chunk_text(text, size=800, overlap=150):

    chunks = []

    start = 0

    while start < len(text):

        chunk = text[start:start + size]

        chunks.append(chunk)

        start += size - overlap

    return chunks
