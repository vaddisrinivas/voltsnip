# StatsApi

All URIs are relative to *http://localhost*

| Method | HTTP request | Description |
|------------- | ------------- | -------------|
| [**getStatsApiV1StatsGet**](StatsApi.md#getstatsapiv1statsget) | **GET** /api/v1/stats | Get Stats |



## getStatsApiV1StatsGet

> any getStatsApiV1StatsGet()

Get Stats

### Example

```ts
import {
  Configuration,
  StatsApi,
} from '@vaddisrinivas/voltsnip-client';
import type { GetStatsApiV1StatsGetRequest } from '@vaddisrinivas/voltsnip-client';

async function example() {
  console.log("🚀 Testing @vaddisrinivas/voltsnip-client SDK...");
  const api = new StatsApi();

  try {
    const data = await api.getStatsApiV1StatsGet();
    console.log(data);
  } catch (error) {
    console.error(error);
  }
}

// Run the test
example().catch(console.error);
```

### Parameters

This endpoint does not need any parameter.

### Return type

**any**

### Authorization

No authorization required

### HTTP request headers

- **Content-Type**: Not defined
- **Accept**: `application/json`


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
| **200** | Successful Response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)

