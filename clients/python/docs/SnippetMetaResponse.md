# SnippetMetaResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**title** | **str** |  | [optional] 
**description** | **str** |  | [optional] 
**language** | **str** |  | [optional] 
**tags** | **List[str]** | List of normalized tags associated with this snippet | [optional] 
**kind** | [**SnippetKind**](SnippetKind.md) | The type of snippet (e.g., snippet, skill, prompt, utility, config) | [optional] 
**canonical_key** | **str** |  | [optional] 
**id** | **UUID** |  | 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 
**expires_at** | **datetime** |  | [optional] 
**view_count** | **int** |  | [optional] [default to 0]
**upvote_count** | **int** |  | [optional] [default to 0]
**downvote_count** | **int** |  | [optional] [default to 0]
**reference_count** | **int** |  | [optional] [default to 0]
**status** | **str** |  | [optional] [default to 'active']
**highlighted_url** | **str** |  | [optional] 
**is_hidden** | **bool** |  | [optional] [default to False]
**hidden_reason** | **str** |  | [optional] 
**source** | **str** |  | [optional] [default to 'human']

## Example

```python
from voltsnip_client.models.snippet_meta_response import SnippetMetaResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SnippetMetaResponse from a JSON string
snippet_meta_response_instance = SnippetMetaResponse.from_json(json)
# print the JSON string representation of the object
print(SnippetMetaResponse.to_json())

# convert the object into a dict
snippet_meta_response_dict = snippet_meta_response_instance.to_dict()
# create an instance of SnippetMetaResponse from a dict
snippet_meta_response_from_dict = SnippetMetaResponse.from_dict(snippet_meta_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


