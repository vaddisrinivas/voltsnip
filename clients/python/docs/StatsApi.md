# voltsnip_client.StatsApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**get_stats_api_v1_stats_get**](StatsApi.md#get_stats_api_v1_stats_get) | **GET** /api/v1/stats | Get Stats


# **get_stats_api_v1_stats_get**
> object get_stats_api_v1_stats_get()

Get Stats

### Example


```python
import voltsnip_client
from voltsnip_client.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = voltsnip_client.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with voltsnip_client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = voltsnip_client.StatsApi(api_client)

    try:
        # Get Stats
        api_response = api_instance.get_stats_api_v1_stats_get()
        print("The response of StatsApi->get_stats_api_v1_stats_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling StatsApi->get_stats_api_v1_stats_get: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

**object**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

