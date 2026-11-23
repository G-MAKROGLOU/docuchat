# Document file

`GET /api/v1/documents/{id}/file` sends the stored PDF. Without a `Range` header it streams the whole file (200). With one valid byte range it sends that range (206). `GET /api/v1/documents/{id}/file/{filename}` sends the same PDF; the viewer saves a download under the last path segment. With `?download=1` the response is an attachment named after the drug.

The PDF viewer is `PdfViewer` of `@geomak/ui` (pdfjs-dist), in `DocumentViewer.tsx`. The Documents page and the source panel of the chat use it. It requests the file through the frontend proxy. It loads its worker script from the jsdelivr CDN (`https://cdn.jsdelivr.net/npm/pdfjs-dist@<version>/build/pdf.worker.min.mjs`), so the viewer needs internet access.

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser (PdfViewer, pdfjs-dist)
    participant CDN as jsdelivr CDN
    participant P as Frontend proxy route.ts
    participant R as get_document_file (documents.py)
    participant Repo as PostgresDocumentRepository
    participant S as DocumentStore (S3)

    B->>CDN: GET pdf.worker.min.mjs (pinned pdfjs-dist version)
    B->>P: GET /api/v1/documents/{id}/file [Range] [?download=1]
    P->>R: GET BACKEND_URL/api/v1/documents/{id}/file, headers copied without hop-by-hop
    Note over P: 35 s limit for the response headers only<br/>timeout: 504, backend not reachable: 502
    R->>Repo: get(document_id)
    alt unknown document
        Repo-->>R: None
        R-->>P: 404 Document not found
    else document found
        Repo-->>R: Document(size_bytes, sha256, storage_key)
        Note over R: headers: Accept-Ranges bytes, ETag "sha256",<br/>Content-Disposition inline, filename id.pdf<br/>(download=1: attachment, UTF-8 name from the brand)
        R->>R: parse_range(Range header, size_bytes)
        alt range starts at or after size, or suffix bytes=-0
            R-->>P: 416, Content-Range bytes */size
        else no Range header, or bad or multi-range header
            R->>S: get_stream(storage_key)
            R->>S: read first 64 KiB block before the headers go out
            alt object missing
                S-->>R: ObjectNotFoundError
                R-->>P: 404 Document file not found
            else object found
                R-->>P: 200 StreamingResponse application/pdf, Content-Length size
                loop remaining 64 KiB blocks
                    S-->>R: bytes
                    R-->>P: bytes
                end
            end
        else one valid range start-end
            R->>S: get_range(storage_key, start, end)
            alt object missing
                S-->>R: ObjectNotFoundError
                R-->>P: 404 Document file not found
            else object found
                S-->>R: bytes start..end
                R-->>P: 206 application/pdf, Content-Range bytes start-end/size
            end
        end
    end
    P-->>B: same status and body, streamed without buffering
```

`RequestIdMiddleware` adds `x-request-id` to every response, logs the request and counts it in the HTTP metrics.

## Thumbnail

`GET /api/v1/documents/{id}/thumbnail` sends a PNG of the first PDF page, 320 pixels wide. The Documents page shows it. The PNG goes into the shared Redis cache, so one render serves all API processes.

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant P as Frontend proxy route.ts
    participant R as get_document_thumbnail (documents.py)
    participant Repo as PostgresDocumentRepository
    participant C as Cache (Redis)
    participant S as DocumentStore (S3)

    B->>P: GET /api/v1/documents/{id}/thumbnail [If-None-Match]
    P->>R: same request
    R->>Repo: get(document_id)
    alt unknown document
        R-->>P: 404 Document not found
    else document found
        Note over R: ETag "sha256-w320", Cache-Control public, max-age=86400
        alt If-None-Match has the ETag
            R-->>P: 304
        else no match
            R->>C: get thumbnail:storage_key:etag
            alt cache hit
                C-->>R: PNG
            else miss or cache error
                Note over R: at most 4 renders at a time per process
                R->>S: get_stream(storage_key), whole PDF
                Note over R,S: object missing: 404 Document file not found
                R->>R: PyMuPdfPageRenderer.render_first_page(pdf, 320)
                R->>C: set PNG, 30 days
            end
            R-->>P: 200 image/png
        end
    end
    P-->>B: same status and body
```
