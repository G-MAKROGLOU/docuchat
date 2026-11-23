# Document file

`GET /api/v1/documents/{id}/file` sends the stored PDF. Without a `Range` header it streams the whole file (200). With one valid byte range it sends that range (206). The PDF viewer in `DocumentViewer.tsx` requests the file through the frontend proxy.

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser (PdfViewer, pdfjs-dist)
    participant P as Frontend proxy route.ts
    participant R as get_document_file (documents.py)
    participant Repo as PostgresDocumentRepository
    participant S as DocumentStore (S3)

    B->>P: GET /api/v1/documents/{id}/file [Range]
    P->>R: GET BACKEND_URL/api/v1/documents/{id}/file, headers copied without hop-by-hop
    R->>Repo: get(document_id)
    alt unknown document
        Repo-->>R: None
        R-->>P: 404 Document not found
    else document found
        Repo-->>R: Document(size_bytes, sha256, storage_key)
        Note over R: headers: Accept-Ranges bytes, ETag "sha256",<br/>Content-Disposition inline, filename id.pdf
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

`RequestIdMiddleware` adds `x-request-id` to every response and logs the request.
