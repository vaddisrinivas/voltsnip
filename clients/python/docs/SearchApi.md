# voltsnip_client.SearchApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**search_api_v1_search_get**](SearchApi.md#search_api_v1_search_get) | **GET** /api/v1/search/ | Search
[**semantic_search_api_v1_search_semantic_get**](SearchApi.md#semantic_search_api_v1_search_semantic_get) | **GET** /api/v1/search/semantic | Semantic Search


# **search_api_v1_search_get**
> List[SnippetMetaResponse] search_api_v1_search_get(tag=tag, language=language, title=title, limit=limit, offset=offset)

Search

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
    api_instance = voltsnip_client.SearchApi(api_client)
    tag = 'tag_example' # str |  (optional)
    language = 'language_example' # str |  (optional)
    title = 'title_example' # str |  (optional)
    limit = 50 # int |  (optional) (default to 50)
    offset = 0 # int |  (optional) (default to 0)

    try:
        # Search
        api_response = api_instance.search_api_v1_search_get(tag=tag, language=language, title=title, limit=limit, offset=offset)
        print("The response of SearchApi->search_api_v1_search_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SearchApi->search_api_v1_search_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **tag** | **str**|  | [optional] 
 **language** | **str**|  | [optional] 
 **title** | **str**|  | [optional] 
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

# **semantic_search_api_v1_search_semantic_get**
> List[SnippetMetaResponse] semantic_search_api_v1_search_semantic_get(q, k=k)

Semantic Search

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
    api_instance = voltsnip_client.SearchApi(api_client)
    q = 'q_example' # str | 
    k = 20 # int |  (optional) (default to 20)

    try:
        # Semantic Search
        api_response = api_instance.semantic_search_api_v1_search_semantic_get(q, k=k)
        print("The response of SearchApi->semantic_search_api_v1_search_semantic_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SearchApi->semantic_search_api_v1_search_semantic_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **q** | **str**|  | 
 **k** | **int**|  | [optional] [default to 20]

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

