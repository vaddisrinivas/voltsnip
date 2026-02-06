# SearchApi

All URIs are relative to *http://localhost*

| Method | HTTP request | Description |
|------------- | ------------- | -------------|
| [**searchApiV1SearchGet**](SearchApi.md#searchapiv1searchget) | **GET** /api/v1/search/ | Search |
| [**semanticSearchApiV1SearchSemanticGet**](SearchApi.md#semanticsearchapiv1searchsemanticget) | **GET** /api/v1/search/semantic | Semantic Search |



## searchApiV1SearchGet

> Array&lt;SnippetMetaResponse&gt; searchApiV1SearchGet(tag, language, title, limit, offset)

Search

### Example

```ts
import {
  Configuration,
  SearchApi,
} from '@vaddisrinivas/voltsnip-client';
import type { SearchApiV1SearchGetRequest } from '@vaddisrinivas/voltsnip-client';

async function example() {
  console.log("🚀 Testing @vaddisrinivas/voltsnip-client SDK...");
  const api = new SearchApi();

  const body = {
    // string (optional)
    tag: tag_example,
    // string (optional)
    language: language_example,
    // string (optional)
    title: title_example,
    // number (optional)
    limit: 56,
    // number (optional)
    offset: 56,
  } satisfies SearchApiV1SearchGetRequest;

  try {
    const data = await api.searchApiV1SearchGet(body);
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
| **tag** | `string` |  | [Optional] [Defaults to `undefined`] |
| **language** | `string` |  | [Optional] [Defaults to `undefined`] |
| **title** | `string` |  | [Optional] [Defaults to `undefined`] |
| **limit** | `number` |  | [Optional] [Defaults to `50`] |
| **offset** | `number` |  | [Optional] [Defaults to `0`] |

### Return type

[**Array&lt;SnippetMetaResponse&gt;**](SnippetMetaResponse.md)

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


## semanticSearchApiV1SearchSemanticGet

> Array&lt;SnippetMetaResponse&gt; semanticSearchApiV1SearchSemanticGet(q, k)

Semantic Search

### Example

```ts
import {
  Configuration,
  SearchApi,
} from '@vaddisrinivas/voltsnip-client';
import type { SemanticSearchApiV1SearchSemanticGetRequest } from '@vaddisrinivas/voltsnip-client';

async function example() {
  console.log("🚀 Testing @vaddisrinivas/voltsnip-client SDK...");
  const api = new SearchApi();

  const body = {
    // string
    q: q_example,
    // number (optional)
    k: 56,
  } satisfies SemanticSearchApiV1SearchSemanticGetRequest;

  try {
    const data = await api.semanticSearchApiV1SearchSemanticGet(body);
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
| **q** | `string` |  | [Defaults to `undefined`] |
| **k** | `number` |  | [Optional] [Defaults to `20`] |

### Return type

[**Array&lt;SnippetMetaResponse&gt;**](SnippetMetaResponse.md)

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

