# FeedsApi

All URIs are relative to *http://localhost*

| Method | HTTP request | Description |
|------------- | ------------- | -------------|
| [**hotFeedApiV1FeedsHotGet**](FeedsApi.md#hotfeedapiv1feedshotget) | **GET** /api/v1/feeds/hot | Hot Feed |
| [**mostUsedFeedApiV1FeedsMostUsedGet**](FeedsApi.md#mostusedfeedapiv1feedsmostusedget) | **GET** /api/v1/feeds/most-used | Most Used Feed |
| [**topFeedApiV1FeedsTopGet**](FeedsApi.md#topfeedapiv1feedstopget) | **GET** /api/v1/feeds/top | Top Feed |
| [**trendingFeedApiV1FeedsTrendingGet**](FeedsApi.md#trendingfeedapiv1feedstrendingget) | **GET** /api/v1/feeds/trending | Trending Feed |



## hotFeedApiV1FeedsHotGet

> Array&lt;SnippetMetaResponse&gt; hotFeedApiV1FeedsHotGet(limit, offset)

Hot Feed

### Example

```ts
import {
  Configuration,
  FeedsApi,
} from '@vaddisrinivas/voltsnip-client';
import type { HotFeedApiV1FeedsHotGetRequest } from '@vaddisrinivas/voltsnip-client';

async function example() {
  console.log("🚀 Testing @vaddisrinivas/voltsnip-client SDK...");
  const api = new FeedsApi();

  const body = {
    // number (optional)
    limit: 56,
    // number (optional)
    offset: 56,
  } satisfies HotFeedApiV1FeedsHotGetRequest;

  try {
    const data = await api.hotFeedApiV1FeedsHotGet(body);
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


## mostUsedFeedApiV1FeedsMostUsedGet

> Array&lt;SnippetMetaResponse&gt; mostUsedFeedApiV1FeedsMostUsedGet(limit, offset)

Most Used Feed

### Example

```ts
import {
  Configuration,
  FeedsApi,
} from '@vaddisrinivas/voltsnip-client';
import type { MostUsedFeedApiV1FeedsMostUsedGetRequest } from '@vaddisrinivas/voltsnip-client';

async function example() {
  console.log("🚀 Testing @vaddisrinivas/voltsnip-client SDK...");
  const api = new FeedsApi();

  const body = {
    // number (optional)
    limit: 56,
    // number (optional)
    offset: 56,
  } satisfies MostUsedFeedApiV1FeedsMostUsedGetRequest;

  try {
    const data = await api.mostUsedFeedApiV1FeedsMostUsedGet(body);
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


## topFeedApiV1FeedsTopGet

> Array&lt;SnippetMetaResponse&gt; topFeedApiV1FeedsTopGet(limit, offset)

Top Feed

### Example

```ts
import {
  Configuration,
  FeedsApi,
} from '@vaddisrinivas/voltsnip-client';
import type { TopFeedApiV1FeedsTopGetRequest } from '@vaddisrinivas/voltsnip-client';

async function example() {
  console.log("🚀 Testing @vaddisrinivas/voltsnip-client SDK...");
  const api = new FeedsApi();

  const body = {
    // number (optional)
    limit: 56,
    // number (optional)
    offset: 56,
  } satisfies TopFeedApiV1FeedsTopGetRequest;

  try {
    const data = await api.topFeedApiV1FeedsTopGet(body);
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


## trendingFeedApiV1FeedsTrendingGet

> Array&lt;SnippetMetaResponse&gt; trendingFeedApiV1FeedsTrendingGet(limit, offset)

Trending Feed

### Example

```ts
import {
  Configuration,
  FeedsApi,
} from '@vaddisrinivas/voltsnip-client';
import type { TrendingFeedApiV1FeedsTrendingGetRequest } from '@vaddisrinivas/voltsnip-client';

async function example() {
  console.log("🚀 Testing @vaddisrinivas/voltsnip-client SDK...");
  const api = new FeedsApi();

  const body = {
    // number (optional)
    limit: 56,
    // number (optional)
    offset: 56,
  } satisfies TrendingFeedApiV1FeedsTrendingGetRequest;

  try {
    const data = await api.trendingFeedApiV1FeedsTrendingGet(body);
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

