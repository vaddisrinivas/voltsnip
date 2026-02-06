
# SnippetCreate


## Properties

Name | Type
------------ | -------------
`title` | string
`description` | string
`language` | string
`tags` | Array&lt;string&gt;
`kind` | [SnippetKind](SnippetKind.md)
`canonicalKey` | string
`code` | string
`source` | string
`parentId` | string

## Example

```typescript
import type { SnippetCreate } from '@vaddisrinivas/voltsnip-client'

// TODO: Update the object below with actual values
const example = {
  "title": null,
  "description": null,
  "language": null,
  "tags": null,
  "kind": null,
  "canonicalKey": null,
  "code": null,
  "source": null,
  "parentId": null,
} satisfies SnippetCreate

console.log(example)

// Convert the instance to a JSON string
const exampleJSON: string = JSON.stringify(example)
console.log(exampleJSON)

// Parse the JSON string back to an object
const exampleParsed = JSON.parse(exampleJSON) as SnippetCreate
console.log(exampleParsed)
```

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


