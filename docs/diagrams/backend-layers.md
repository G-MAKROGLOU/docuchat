# Backend layers

Dependencies point inward to `app/domain`. `app/wiring.py` (API), `app/worker/wiring.py` (worker) and the entry points connect the adapters to the ports. `app/runtime_defaults.py` holds the runtime-settings defaults that both use. The worker modules do not import the chat code, LangGraph or FastAPI; `tests/test_worker_imports.py` checks this. The first diagram shows the modules and their imports. The second diagram shows which adapter implements which port.

```mermaid
flowchart TB
    subgraph entry["Entry points (app/)"]
        main["main.py<br/>FastAPI app, lifespan"]
        worker["worker/__main__.py<br/>schedule and requested passes"]
        cmds["worker/corpus_init.py<br/>manifest labels into the label queue"]
        rconf["runtime_config.py RuntimeConfig<br/>saved settings, rebuild on change"]
    end

    wiring["wiring.py<br/>API composition root<br/>chat_service(), retrieval_service(),<br/>drug_detector()"]
    wwiring["worker/wiring.py<br/>worker composition root<br/>ingestion_service()"]
    defaults["runtime_defaults.py<br/>default_runtime_settings(), with_models()"]

    subgraph api["app/api"]
        factory["factory.py create_api()<br/>prefix /api/v1, /metrics"]
        routers["routers/: health, documents, chat, status,<br/>ingestion, labels, settings<br/>contract.py: contract router"]
        deps["dependencies.py<br/>reads app.state"]
        mw["middleware.py RequestIdMiddleware"]
        range["http_range.py parse_range()"]
    end

    subgraph application["app/application"]
        chat["chat/ service.py ChatService,<br/>graph.py build_chat_graph()"]
        prompts["chat_prompts.py"]
        topics["topics.py section_hints()"]
        detection["drug_detection.py DrugDetector<br/>versioned_cache.py VersionedCache"]
        retrieval["retrieval.py RetrievalService"]
        fusion["fusion.py fuse(), select()"]
        runner["ingestion_runner.py IngestionRunner"]
        control["ingestion_control.py<br/>IngestionControl, IngestWorker"]
        ingestion["ingestion.py IngestionService"]
        sections["label_sections.py split_sections()"]
        locator["page_locator.py PageLocator"]
        chunking["chunking.py build_chunks(),<br/>table_context(), embedding_input()"]
        corpus["corpus.py download_corpus()"]
        update["corpus_update.py check_for_updates()"]
        queue["label_queue.py<br/>add_label(), process_queue()"]
        rsettings["runtime_settings.py"]
        ready["readiness.py ReadinessCheck"]
    end

    subgraph domain["app/domain (no framework imports)"]
        d_ports["ports.py"]
        d_docs["documents.py"]
        d_store["storage.py"]
        d_ent["entities.py"]
        d_other["conversations.py, label_queue.py,<br/>ingestion_state.py, runtime_settings.py,<br/>corpus_stats.py"]
    end

    infra["app/infrastructure<br/>adapters: Postgres, S3, Redis, OpenRouter,<br/>DailyMed, PyMuPDF, SPL XML, RapidFuzz, Langfuse,<br/>metrics, logging, migrations"]

    main --> factory
    main --> wiring
    main --> infra
    main --> rconf
    worker --> wwiring
    worker --> runner
    worker --> control
    worker --> infra
    worker --> rconf
    cmds --> corpus
    cmds --> infra
    wiring --> application
    wiring --> infra
    wiring --> defaults
    wwiring --> application
    wwiring --> infra
    wwiring --> defaults

    factory --> routers
    factory --> mw
    routers --> deps
    routers --> range
    routers --> application
    routers --> domain
    deps --> infra

    chat --> prompts
    chat --> topics
    chat --> detection
    chat --> retrieval
    retrieval --> fusion
    runner --> ingestion
    runner --> update
    runner --> queue
    queue --> corpus
    queue --> ingestion
    update --> corpus
    ingestion --> sections
    ingestion --> locator
    ingestion --> chunking
    chunking --> sections
    rconf --> rsettings

    application --> domain
    infra -.->|"implements"| domain
```

Port to adapter map. The ports are in `app/domain` unless the label names `application`.

```mermaid
flowchart LR
    ChatModelProvider --> RoleModels
    ChatModel --> CachedChatModel["CachedChatModel<br/>chat and rewrite roles"]
    ChatModel --> OpenRouterChatModel["OpenRouterChatModel<br/>with OpenRouterStreamChat"]
    CachedChatModel -.->|wraps| OpenRouterChatModel
    Embedder --> CachedEmbedder
    Embedder --> OpenRouterEmbedder
    CachedEmbedder -.->|wraps| OpenRouterEmbedder
    Cache --> RedisCache
    ChunkRepository --> PostgresChunkRepository
    ChunkSearch --> PostgresChunkSearch
    DocumentRepository --> PostgresDocumentRepository
    IngestionStatusRepository --> PostgresDocumentRepository
    DocumentLocks --> PostgresDocumentLocks
    ConversationRepository --> PostgresConversationRepository
    LabelQueueRepository --> PostgresLabelQueueRepository
    IngestionStateRepository --> PostgresIngestionStateRepository
    RuntimeSettingsRepository --> PostgresRuntimeSettingsRepository
    CorpusStatsRepository --> CachedCorpusStats
    CorpusStatsRepository --> PostgresCorpusStatsRepository
    CachedCorpusStats -.->|wraps| PostgresCorpusStatsRepository
    LabelSource --> DailyMedClient
    LabelCatalog --> DailyMedCatalog
    DocumentStore --> S3DocumentStore
    DocumentStore --> FileSystemDocumentStore
    DocumentParser --> PyMuPdfParser
    PageRenderer --> PyMuPdfPageRenderer
    LabelParser --> SplXmlParser
    LabelMetadataReader --> SplXmlParser
    TextSplitter --> SentenceTokenSplitter
    TokenCounter --> TiktokenCounter
    NameSimilarity --> RapidFuzzSimilarity
    TurnTracer --> LangfuseTracer
    TurnTracer --> NoopTracer
    Retriever["Retriever (application)"] --> RetrievalService
    DetectorSource["DetectorSource (application)"] --> VersionedCache
```
