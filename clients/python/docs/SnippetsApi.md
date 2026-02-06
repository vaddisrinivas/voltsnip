# voltsnip_client.SnippetsApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**create_snippet_api_v1_snippets_post**](SnippetsApi.md#create_snippet_api_v1_snippets_post) | **POST** /api/v1/snippets/ | Create Snippet
[**read_snippet_api_v1_snippets_snippet_id_get**](SnippetsApi.md#read_snippet_api_v1_snippets_snippet_id_get) | **GET** /api/v1/snippets/{snippet_id} | Read Snippet
[**view_snippet_api_v1_snippets_snippet_id_view_post**](SnippetsApi.md#view_snippet_api_v1_snippets_snippet_id_view_post) | **POST** /api/v1/snippets/{snippet_id}/view | View Snippet
[**vote_snippet_api_v1_snippets_snippet_id_vote_post**](SnippetsApi.md#vote_snippet_api_v1_snippets_snippet_id_vote_post) | **POST** /api/v1/snippets/{snippet_id}/vote | Vote Snippet


# **create_snippet_api_v1_snippets_post**
> SnippetDetailResponse create_snippet_api_v1_snippets_post(snippet_create)

Create Snippet

### Example


```python
import voltsnip_client
from voltsnip_client.models.snippet_create import SnippetCreate
from voltsnip_client.models.snippet_detail_response import SnippetDetailResponse
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
    api_instance = voltsnip_client.SnippetsApi(api_client)
    snippet_create = voltsnip_client.SnippetCreate() # SnippetCreate | 

    try:
        # Create Snippet
        api_response = api_instance.create_snippet_api_v1_snippets_post(snippet_create)
        print("The response of SnippetsApi->create_snippet_api_v1_snippets_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SnippetsApi->create_snippet_api_v1_snippets_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **snippet_create** | [**SnippetCreate**](SnippetCreate.md)|  | 

### Return type

[**SnippetDetailResponse**](SnippetDetailResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **read_snippet_api_v1_snippets_snippet_id_get**
> SnippetDetailResponse read_snippet_api_v1_snippets_snippet_id_get(snippet_id)

Read Snippet

### Example


```python
import voltsnip_client
from voltsnip_client.models.snippet_detail_response import SnippetDetailResponse
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
    api_instance = voltsnip_client.SnippetsApi(api_client)
    snippet_id = UUID('38400000-8cf0-11bd-b23e-10b96e4ef00d') # UUID | 

    try:
        # Read Snippet
        api_response = api_instance.read_snippet_api_v1_snippets_snippet_id_get(snippet_id)
        print("The response of SnippetsApi->read_snippet_api_v1_snippets_snippet_id_get:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SnippetsApi->read_snippet_api_v1_snippets_snippet_id_get: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **snippet_id** | **UUID**|  | 

### Return type

[**SnippetDetailResponse**](SnippetDetailResponse.md)

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

# **view_snippet_api_v1_snippets_snippet_id_view_post**
> SnippetMetaResponse view_snippet_api_v1_snippets_snippet_id_view_post(snippet_id)

View Snippet

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
    api_instance = voltsnip_client.SnippetsApi(api_client)
    snippet_id = UUID('38400000-8cf0-11bd-b23e-10b96e4ef00d') # UUID | 

    try:
        # View Snippet
        api_response = api_instance.view_snippet_api_v1_snippets_snippet_id_view_post(snippet_id)
        print("The response of SnippetsApi->view_snippet_api_v1_snippets_snippet_id_view_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SnippetsApi->view_snippet_api_v1_snippets_snippet_id_view_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **snippet_id** | **UUID**|  | 

### Return type

[**SnippetMetaResponse**](SnippetMetaResponse.md)

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

# **vote_snippet_api_v1_snippets_snippet_id_vote_post**
> SnippetMetaResponse vote_snippet_api_v1_snippets_snippet_id_vote_post(snippet_id, vote)

Vote Snippet

### Example


```python
import voltsnip_client
from voltsnip_client.models.snippet_meta_response import SnippetMetaResponse
from voltsnip_client.models.vote import Vote
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
    api_instance = voltsnip_client.SnippetsApi(api_client)
    snippet_id = UUID('38400000-8cf0-11bd-b23e-10b96e4ef00d') # UUID | 
    vote = voltsnip_client.Vote() # Vote | 

    try:
        # Vote Snippet
        api_response = api_instance.vote_snippet_api_v1_snippets_snippet_id_vote_post(snippet_id, vote)
        print("The response of SnippetsApi->vote_snippet_api_v1_snippets_snippet_id_vote_post:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SnippetsApi->vote_snippet_api_v1_snippets_snippet_id_vote_post: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **snippet_id** | **UUID**|  | 
 **vote** | [**Vote**](Vote.md)|  | 

### Return type

[**SnippetMetaResponse**](SnippetMetaResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

