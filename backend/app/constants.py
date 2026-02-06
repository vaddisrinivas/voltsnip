ACTIVE_STATUS = "active"
EXPIRED_STATUS = "expired"
SURVIVED_STATUS = "survived"
SURVIVAL_UPVOTES = 5
SURVIVAL_VIEWS = 50
SURVIVAL_REFERENCES = 3

KEY_SNIPPETS = "total_snippets"
KEY_VIEWS = "total_views"
KEY_UPVOTES = "total_upvotes"
KEY_DOWNVOTES = "total_downvotes"

# Route paths
API_PREFIX = "/api/v1"
FEEDS_PREFIX = "/feeds"
SEARCH_PREFIX = "/search"
SNIPPETS_PREFIX = "/snippets"
STATS_PATH = "/api/v1/stats"
HEALTH_PATH = "/health"
MCP_PATH = "/mcp"
DOCS_PATH = "/docs"
REDOC_PATH = "/redoc"
OPENAPI_PATH = "/openapi.json"

FEEDS_TRENDING_PATH = "/trending"
FEEDS_HOT_PATH = "/hot"
FEEDS_TOP_PATH = "/top"
FEEDS_MOST_USED_PATH = "/most-used"

SEARCH_ROOT_PATH = "/"
SEARCH_SEMANTIC_PATH = "/semantic"

SNIPPETS_ROOT_PATH = "/"
SNIPPET_BY_ID_PATH = "/{snippet_id}"
SNIPPET_VIEW_PATH = "/{snippet_id}/view"
SNIPPET_VOTE_PATH = "/{snippet_id}/vote"

# Route tags
FEEDS_TAG = "feeds"
SEARCH_TAG = "search"
SNIPPETS_TAG = "snippets"
STATS_TAG = "stats"
HEALTH_TAG = "health"

# App metadata and headers
APP_TITLE = "VoltSnip HTTP API"
DEFAULT_APP_VERSION = "0.1.0"
MIDDLEWARE_HTTP = "http"
GATEWAY_SECRET_HEADER = "X-Gateway-Secret"
GATEWAY_FORBIDDEN_DETAIL = (
    "Direct access forbidden. Use the public API endpoint."
)

HEALTH_STATUS_KEY = "status"
HEALTH_STATUS_OK = "ok"

MCP_MOUNT_LOG = "MCP mounted at %s"
MCP_MOUNT_FAILED_LOG = "MCP mount failed: %s"

MCP_INTERNAL_PATH = "/"
SETTINGS_VERSION_ATTR = "VERSION"
MCP_SNIPPETS_RESOURCE = "resource://snippets"
MCP_SNIPPET_RESOURCE = "resource://snippets/{snippet_id}"
MCP_SNIPPETS_BY_TAG_RESOURCE = "resource://snippets/by-tag/{tag}"
MCP_SNIPPETS_BY_TITLE_RESOURCE = "resource://snippets/by-title/{title}"
MCP_SNIPPETS_BY_LANGUAGE_RESOURCE = "resource://snippets/by-language/{language}"
MCP_SNIPPET_INVALID_ID = "invalid snippet id"
MCP_SNIPPET_NOT_FOUND = "snippet not found"
MCP_INVALID_FILTER = "invalid filter"

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
BOTOCORO_LOGGER_NAME = "botocore"
URLLIB3_LOGGER_NAME = "urllib3"

SETTINGS_CORS_ORIGINS_ATTR = "CORS_ORIGINS"
CORS_ALLOW_ALL = "*"
ALLOW_METHODS_ALL = ["*"]
ALLOW_HEADERS_ALL = ["*"]
DEFAULT_CORS_ORIGINS = [CORS_ALLOW_ALL]

ERROR_DETAIL_KEY = "detail"

# Cache defaults
DEFAULT_FEED_CACHE_TTL_SECONDS = 30
FEED_CACHE_KEY_TEMPLATE = "feed:%s:%s:%s"
DEFAULT_SNIPPET_CACHE_TTL_SECONDS = 0
SNIPPET_CACHE_KEY_TEMPLATE = "snippet:%s"
DEFAULT_SNIPPET_CACHE_MAX_AGE_SECONDS = 300

# General strings
EMPTY_STRING = ""
SPACE = " "
DOT = "."
COMMA = ","
LEFT_BRACKET = "["
RIGHT_BRACKET = "]"
PRIVATE_ATTR_PREFIX = "_"
PLATFORM_WIN32 = "win32"
QUERY_SEPARATOR = "?"

# Logger names
VOLTSNIP_LOGGER_NAME = "voltsnip"

# Storage providers and defaults
STORAGE_PROVIDER_S3 = "s3"
STORAGE_PROVIDER_AZURE = "azure"
STORAGE_PROVIDER_LOCAL = "local"
DEFAULT_STORAGE_BUCKET_NAME = "local-bucket"
DEFAULT_AWS_REGION = "us-east-1"
DEFAULT_STORAGE_PROVIDER = STORAGE_PROVIDER_LOCAL
DEFAULT_STORAGE_ROOT = "local_storage"
FILE_URI_PREFIX = "file://"

# File I/O
FILE_MODE_READ = "r"
FILE_MODE_WRITE = "w"
ENCODING_UTF8 = "utf-8"
SNIPPET_META_EXTENSION = ".json"
SNIPPET_META_SCHEMA = "voltsnip.snippet.meta.v1"
SNIPPET_META_VERSION = 1

# Embeddings
EMBEDDINGS_MODEL_DEFAULT = "BAAI/bge-small-en-v1.5"
EMBEDDINGS_MODEL_ATTR = "embed"
EMBEDDING_MODEL_UNKNOWN = "unknown"

# Boto3
BOTO3_SERVICE_S3 = "s3"
BOTO3_BODY_KEY = "Body"

# Azure storage logs
AZURE_STORAGE_IMPORT_ERROR = "azure-storage-blob not installed."
AZURE_STORAGE_INIT_FAILED_LOG = "Failed to initialize Azure Storage: %s"
S3_STORAGE_IMPORT_ERROR = "aioboto3 not installed."
S3_STORAGE_INIT_FAILED_LOG = "Failed to initialize S3 storage: %s"

# Storage logs
UPLOAD_ERROR_LOG = "Upload Error: %s"

# Embeddings logs
EMBEDDING_MODEL_LOADING_LOG = "Loading embedding model: %s"
EMBEDDING_MODEL_NOT_FOUND_LOG = "FastEmbed model %s not found, falling back to default."
EMBEDDINGS_DISABLED_LOG = "Embedding generation requested but service is disabled."
EMBEDDING_GENERATION_FAILED_LOG = "Embedding generation failed: %s"

# Config
SETTINGS_EXTRA_IGNORE = "ignore"
SETTINGS_EXTRA_FORBID = "forbid"
ENV_FILE_NAME = ".env"
SETTINGS_CORS_ORIGINS_FIELD = "CORS_ORIGINS"
VALIDATOR_MODE_BEFORE = "before"
MIGRATION_DB_ASYNC_PREFIX = "postgresql+asyncpg"
MIGRATION_DB_SYNC_PREFIX = "postgresql+psycopg"
SSL_MODE_PARAM = "sslmode"
NEONDB_HOST_MARKER = "neondb"
NEON_TECH_HOST_MARKER = "neon.tech"
SSL_CONNECT_ARG_KEY = "ssl"
SSL_CONNECT_ARG_VALUE = "require"

# DB defaults and schema
SERVER_DEFAULT_ZERO = "0"
SERVER_DEFAULT_ONE = "1"
SERVER_DEFAULT_FALSE = "false"
EMPTY_PG_ARRAY_TEXT = "'{}'"
FK_ONDELETE_CASCADE = "CASCADE"
POSTGRES_USING_GIN = "gin"
POSTGRES_USING_HNSW = "hnsw"
POSTGRES_VECTOR_OPS_KEY = "vector"
POSTGRES_VECTOR_OPS_VALUE = "vector_cosine_ops"
EPOCH_EXTRACT_KEY = "EPOCH"

# Table names
TABLE_SNIPPETS = "snippets"
TABLE_SNIPPET_EMBEDDINGS = "snippet_embeddings"
TABLE_STATS = "stats"
TABLE_SNIPPET_REFERENCES = "snippet_references"
FK_SNIPPETS_ID = f"{TABLE_SNIPPETS}.id"

# Index names
IDX_SNIPPETS_EXPIRES_AT = "idx_snippets_expires_at"
IDX_SNIPPETS_CREATED_AT = "idx_snippets_created_at"
IDX_SNIPPETS_UPVOTES = "idx_snippets_upvotes"
IDX_SNIPPETS_TAGS = "idx_snippets_tags"
IDX_SNIPPETS_STATUS = "idx_snippets_status"
IDX_SNIPPETS_SOURCE_HASH = "idx_snippets_source_hash"
IDX_SNIPPETS_VISIBILITY = "idx_snippets_visibility"
IDX_SNIPPETS_LANGUAGE = "idx_snippets_language"
IDX_SNIPPETS_KIND = "idx_snippets_kind"
IDX_SNIPPETS_CANONICAL = "idx_snippets_canonical"
IDX_SNIPPET_EMBEDDINGS_SNIPPET_ID = "idx_snippet_embeddings_snippet_id"
IDX_SNIPPET_EMBEDDINGS_VECTOR = "idx_snippet_embeddings_vector"
IDX_SNIPPET_REFERENCES_PARENT = "idx_snippet_references_parent"
IDX_SNIPPET_REFERENCES_CHILD = "idx_snippet_references_child"

# Snippet kinds and defaults
SNIPPET_KIND_SNIPPET = "snippet"
SNIPPET_KIND_SKILL = "skill"
SNIPPET_KIND_PROMPT = "prompt"
SNIPPET_KIND_UTILITY = "utility"
SNIPPET_KIND_CONFIG = "config"
SNIPPET_SOURCE_DEFAULT = "human"

# Schemas descriptions
DESC_TITLE = "Human-friendly title for the snippet"
DESC_DESCRIPTION = "Context or explanation for the snippet"
DESC_LANGUAGE = "Programming language or format of the snippet"
DESC_TAGS = "List of normalized tags associated with this snippet"
DESC_KIND = "The type of snippet (e.g., snippet, skill, prompt, utility, config)"
DESC_CANONICAL_KEY = (
    "Stable string used to identify the same intent over time (e.g., slug)"
)
DESC_CODE = "The actual code or text content"
DESC_SOURCE = "Source of the snippet (e.g. 'human' or bot name)"
DESC_PARENT_ID = "Optional parent snippet id when creating a new version"

# Schema errors
ERR_TOO_MANY_TAGS = "Too many tags (max 20)"
ERR_TAG_TOO_LONG = "Tag too long: %s (max 50 characters)"
ERR_CANONICAL_HAS_SPACES = "canonical_key cannot contain spaces"
ERR_CANONICAL_EMPTY = "canonical_key cannot be empty"

# Schema field names
FIELD_TAGS = "tags"
FIELD_CANONICAL_KEY = "canonical_key"

# View errors
ERR_SNIPPET_NOT_FOUND = "Snippet not found"
ERR_SNIPPET_TOO_LARGE = "Snippet content exceeds maximum size of %s bytes."
ERR_SEMANTIC_SEARCH_DISABLED = "Semantic search is temporarily disabled."
ERR_UPLOAD_FAILED = "Failed to upload snippet content to storage."

# View logs
LOG_VECTOR_GENERATION_FAILED = "Vector generation failed for snippet: %s"
LOG_UPLOAD_FAILED = "Failed to upload snippet %s to storage."
LOG_UPDATE_STATS_FAILED = "Error updating stats in DB: %s"

# Misc
BLOB_KEY_TEMPLATE = "%s.txt"
DEFAULT_STATS_ID = 1
CONTEXT_SNIPPET_MAX_CHARS = 1000
