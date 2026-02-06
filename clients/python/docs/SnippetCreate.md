# SnippetCreate


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**title** | **str** |  | [optional] 
**description** | **str** |  | [optional] 
**language** | **str** |  | [optional] 
**tags** | **List[str]** | List of normalized tags associated with this snippet | [optional] 
**kind** | [**SnippetKind**](SnippetKind.md) | The type of snippet (e.g., snippet, skill, prompt, utility, config) | [optional] 
**canonical_key** | **str** |  | [optional] 
**code** | **str** | The actual code or text content | 
**source** | **str** |  | [optional] 
**parent_id** | **UUID** |  | [optional] 

## Example

```python
from voltsnip_client.models.snippet_create import SnippetCreate

# TODO update the JSON string below
json = "{}"
# create an instance of SnippetCreate from a JSON string
snippet_create_instance = SnippetCreate.from_json(json)
# print the JSON string representation of the object
print(SnippetCreate.to_json())

# convert the object into a dict
snippet_create_dict = snippet_create_instance.to_dict()
# create an instance of SnippetCreate from a dict
snippet_create_from_dict = SnippetCreate.from_dict(snippet_create_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


