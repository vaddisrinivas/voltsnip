# SnippetsApi

All URIs are relative to *http://localhost*

| Method | HTTP request | Description |
|------------- | ------------- | -------------|
| [**createSnippetApiV1SnippetsPost**](SnippetsApi.md#createsnippetapiv1snippetspost) | **POST** /api/v1/snippets/ | Create Snippet |
| [**readSnippetApiV1SnippetsSnippetIdGet**](SnippetsApi.md#readsnippetapiv1snippetssnippetidget) | **GET** /api/v1/snippets/{snippet_id} | Read Snippet |
| [**readSnippetByCanonicalKeyApiV1SnippetsByKeyCanonicalKeyGet**](SnippetsApi.md#readsnippetbycanonicalkeyapiv1snippetsbykeycanonicalkeyget) | **GET** /api/v1/snippets/by-key/{canonical_key} | Read Snippet By Canonical Key |
| [**viewSnippetApiV1SnippetsSnippetIdViewPost**](SnippetsApi.md#viewsnippetapiv1snippetssnippetidviewpost) | **POST** /api/v1/snippets/{snippet_id}/view | View Snippet |
| [**voteSnippetApiV1SnippetsSnippetIdVotePost**](SnippetsApi.md#votesnippetapiv1snippetssnippetidvotepost) | **POST** /api/v1/snippets/{snippet_id}/vote | Vote Snippet |



## createSnippetApiV1SnippetsPost

> SnippetDetailResponse createSnippetApiV1SnippetsPost(snippetCreate)

Create Snippet

### Example

```ts
import {
  Configuration,
  SnippetsApi,
} from '@vaddisrinivas/voltsnip-client';
import type { CreateSnippetApiV1SnippetsPostRequest } from '@vaddisrinivas/voltsnip-client';

async function example() {
  console.log("🚀 Testing @vaddisrinivas/voltsnip-client SDK...");
  const api = new SnippetsApi();

  const body = {
    // SnippetCreate
    snippetCreate: ...,
  } satisfies CreateSnippetApiV1SnippetsPostRequest;

  try {
    const data = await api.createSnippetApiV1SnippetsPost(body);
    console.log(data);
  } catch (error) {
    console.error(error);
  }
}

// Run the test
example().catch(console.error);
```

### Parameters


| Name | Type | Description  | Notes |
|------------- | ------------- | ------------- | -------------|
| **snippetCreate** | [SnippetCreate](SnippetCreate.md) |  | |

### Return type

[**SnippetDetailResponse**](SnippetDetailResponse.md)

### Authorization

No authorization required

### HTTP request headers

- **Content-Type**: `application/json`
- **Accept**: `application/json`


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful Response |  -  |
| **422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


## readSnippetApiV1SnippetsSnippetIdGet

> SnippetDetailResponse readSnippetApiV1SnippetsSnippetIdGet(snippetId)

Read Snippet

### Example

```ts
import {
  Configuration,
  SnippetsApi,
} from '@vaddisrinivas/voltsnip-client';
import type { ReadSnippetApiV1SnippetsSnippetIdGetRequest } from '@vaddisrinivas/voltsnip-client';

async function example() {
  console.log("🚀 Testing @vaddisrinivas/voltsnip-client SDK...");
  const api = new SnippetsApi();

  const body = {
    // string
    snippetId: 38400000-8cf0-11bd-b23e-10b96e4ef00d,
  } satisfies ReadSnippetApiV1SnippetsSnippetIdGetRequest;

  try {
    const data = await api.readSnippetApiV1SnippetsSnippetIdGet(body);
    console.log(data);
  } catch (error) {
    console.error(error);
  }
}

// Run the test
example().catch(console.error);
```

### Parameters


| Name | Type | Description  | Notes |
|------------- | ------------- | ------------- | -------------|
| **snippetId** | `string` |  | [Defaults to `undefined`] |

### Return type

[**SnippetDetailResponse**](SnippetDetailResponse.md)

### Authorization

No authorization required

### HTTP request headers

- **Content-Type**: Not defined
- **Accept**: `application/json`


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful Response |  -  |
| **422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


## readSnippetByCanonicalKeyApiV1SnippetsByKeyCanonicalKeyGet

> SnippetDetailResponse readSnippetByCanonicalKeyApiV1SnippetsByKeyCanonicalKeyGet(canonicalKey)

Read Snippet By Canonical Key

Retrieve a snippet by its canonical_key (slash-delimited path).

### Example

```ts
import {
  Configuration,
  SnippetsApi,
} from '@vaddisrinivas/voltsnip-client';
import type { ReadSnippetByCanonicalKeyApiV1SnippetsByKeyCanonicalKeyGetRequest } from '@vaddisrinivas/voltsnip-client';

async function example() {
  console.log("🚀 Testing @vaddisrinivas/voltsnip-client SDK...");
  const api = new SnippetsApi();

  const body = {
    // string
    canonicalKey: canonicalKey_example,
  } satisfies ReadSnippetByCanonicalKeyApiV1SnippetsByKeyCanonicalKeyGetRequest;

  try {
    const data = await api.readSnippetByCanonicalKeyApiV1SnippetsByKeyCanonicalKeyGet(body);
    console.log(data);
  } catch (error) {
    console.error(error);
  }
}

// Run the test
example().catch(console.error);
```

### Parameters


| Name | Type | Description  | Notes |
|------------- | ------------- | ------------- | -------------|
| **canonicalKey** | `string` |  | [Defaults to `undefined`] |

### Return type

[**SnippetDetailResponse**](SnippetDetailResponse.md)

### Authorization

No authorization required

### HTTP request headers

- **Content-Type**: Not defined
- **Accept**: `application/json`


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful Response |  -  |
| **422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


## viewSnippetApiV1SnippetsSnippetIdViewPost

> SnippetMetaResponse viewSnippetApiV1SnippetsSnippetIdViewPost(snippetId)

View Snippet

### Example

```ts
import {
  Configuration,
  SnippetsApi,
} from '@vaddisrinivas/voltsnip-client';
import type { ViewSnippetApiV1SnippetsSnippetIdViewPostRequest } from '@vaddisrinivas/voltsnip-client';

async function example() {
  console.log("🚀 Testing @vaddisrinivas/voltsnip-client SDK...");
  const api = new SnippetsApi();

  const body = {
    // string
    snippetId: 38400000-8cf0-11bd-b23e-10b96e4ef00d,
  } satisfies ViewSnippetApiV1SnippetsSnippetIdViewPostRequest;

  try {
    const data = await api.viewSnippetApiV1SnippetsSnippetIdViewPost(body);
    console.log(data);
  } catch (error) {
    console.error(error);
  }
}

// Run the test
example().catch(console.error);
```

### Parameters


| Name | Type | Description  | Notes |
|------------- | ------------- | ------------- | -------------|
| **snippetId** | `string` |  | [Defaults to `undefined`] |

### Return type

[**SnippetMetaResponse**](SnippetMetaResponse.md)

### Authorization

No authorization required

### HTTP request headers

- **Content-Type**: Not defined
- **Accept**: `application/json`


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful Response |  -  |
| **422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


## voteSnippetApiV1SnippetsSnippetIdVotePost

> SnippetMetaResponse voteSnippetApiV1SnippetsSnippetIdVotePost(snippetId, vote)

Vote Snippet

### Example

```ts
import {
  Configuration,
  SnippetsApi,
} from '@vaddisrinivas/voltsnip-client';
import type { VoteSnippetApiV1SnippetsSnippetIdVotePostRequest } from '@vaddisrinivas/voltsnip-client';

async function example() {
  console.log("🚀 Testing @vaddisrinivas/voltsnip-client SDK...");
  const api = new SnippetsApi();

  const body = {
    // string
    snippetId: 38400000-8cf0-11bd-b23e-10b96e4ef00d,
    // Vote
    vote: ...,
  } satisfies VoteSnippetApiV1SnippetsSnippetIdVotePostRequest;

  try {
    const data = await api.voteSnippetApiV1SnippetsSnippetIdVotePost(body);
    console.log(data);
  } catch (error) {
    console.error(error);
  }
}

// Run the test
example().catch(console.error);
```

### Parameters


| Name | Type | Description  | Notes |
|------------- | ------------- | ------------- | -------------|
| **snippetId** | `string` |  | [Defaults to `undefined`] |
| **vote** | [Vote](Vote.md) |  | |

### Return type

[**SnippetMetaResponse**](SnippetMetaResponse.md)

### Authorization

No authorization required

### HTTP request headers

- **Content-Type**: `application/json`
- **Accept**: `application/json`


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful Response |  -  |
| **422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)

