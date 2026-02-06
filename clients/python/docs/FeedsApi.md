# voltsnip_client.FeedsApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**hot_feed_api_v1_feeds_hot_get**](FeedsApi.md#hot_feed_api_v1_feeds_hot_get) | **GET** /api/v1/feeds/hot | Hot Feed
[**most_used_feed_api_v1_feeds_most_used_get**](FeedsApi.md#most_used_feed_api_v1_feeds_most_used_get) | **GET** /api/v1/feeds/most-used | Most Used Feed
[**top_feed_api_v1_feeds_top_get**](FeedsApi.md#top_feed_api_v1_feeds_top_get) | **GET** /api/v1/feeds/top | Top Feed
[**trending_feed_api_v1_feeds_trending_get**](FeedsApi.md#trending_feed_api_v1_feeds_trending_get) | **GET** /api/v1/feeds/trending | Trending Feed


# **hot_feed_api_v1_feeds_hot_get**
> List[SnippetMetaResponse] hot_feed_api_v1_feeds_hot_get(limit=limit, offset=offset)

Hot Feed

### Example


```python
import voltsnip_client
from voltsnip_client.models.snippet_meta_response import SnippetMetaResponse
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
    api_instance = voltsnip_client.FeedsApi(api_client)
    limit = 50 # int |  (optional) (default to 50)
    offset = 0 # int |  (optional) (default to 0)

    try:
        # Hot Feed
        api_response = api_instance.hot_feed_api_v1_feeds_hot_get(limit=limit, offset=offset)
        print("The response of FeedsApi->hot_feed_api_v1_feeds_hot_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling FeedsApi->hot_feed_api_v1_feeds_hot_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **limit** | **int**|  | [optional] [default to 50]
 **offset** | **int**|  | [optional] [default to 0]

### Return type

[**List[SnippetMetaResponse]**](SnippetMetaResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **most_used_feed_api_v1_feeds_most_used_get**
> List[SnippetMetaResponse] most_used_feed_api_v1_feeds_most_used_get(limit=limit, offset=offset)

Most Used Feed

### Example


```python
import voltsnip_client
from voltsnip_client.models.snippet_meta_response import SnippetMetaResponse
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
    api_instance = voltsnip_client.FeedsApi(api_client)
    limit = 50 # int |  (optional) (default to 50)
    offset = 0 # int |  (optional) (default to 0)

    try:
        # Most Used Feed
        api_response = api_instance.most_used_feed_api_v1_feeds_most_used_get(limit=limit, offset=offset)
        print("The response of FeedsApi->most_used_feed_api_v1_feeds_most_used_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling FeedsApi->most_used_feed_api_v1_feeds_most_used_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **limit** | **int**|  | [optional] [default to 50]
 **offset** | **int**|  | [optional] [default to 0]

### Return type

[**List[SnippetMetaResponse]**](SnippetMetaResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **top_feed_api_v1_feeds_top_get**
> List[SnippetMetaResponse] top_feed_api_v1_feeds_top_get(limit=limit, offset=offset)

Top Feed

### Example


```python
import voltsnip_client
from voltsnip_client.models.snippet_meta_response import SnippetMetaResponse
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
    api_instance = voltsnip_client.FeedsApi(api_client)
    limit = 50 # int |  (optional) (default to 50)
    offset = 0 # int |  (optional) (default to 0)

    try:
        # Top Feed
        api_response = api_instance.top_feed_api_v1_feeds_top_get(limit=limit, offset=offset)
        print("The response of FeedsApi->top_feed_api_v1_feeds_top_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling FeedsApi->top_feed_api_v1_feeds_top_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **limit** | **int**|  | [optional] [default to 50]
 **offset** | **int**|  | [optional] [default to 0]

### Return type

[**List[SnippetMetaResponse]**](SnippetMetaResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **trending_feed_api_v1_feeds_trending_get**
> List[SnippetMetaResponse] trending_feed_api_v1_feeds_trending_get(limit=limit, offset=offset)

Trending Feed

### Example


```python
import voltsnip_client
from voltsnip_client.models.snippet_meta_response import SnippetMetaResponse
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
    api_instance = voltsnip_client.FeedsApi(api_client)
    limit = 50 # int |  (optional) (default to 50)
    offset = 0 # int |  (optional) (default to 0)

    try:
        # Trending Feed
        api_response = api_instance.trending_feed_api_v1_feeds_trending_get(limit=limit, offset=offset)
        print("The response of FeedsApi->trending_feed_api_v1_feeds_trending_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling FeedsApi->trending_feed_api_v1_feeds_trending_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **limit** | **int**|  | [optional] [default to 50]
 **offset** | **int**|  | [optional] [default to 0]

### Return type

[**List[SnippetMetaResponse]**](SnippetMetaResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

