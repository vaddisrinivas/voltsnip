
# SnippetMetaResponse


## Properties

Name | Type
------------ | -------------
`title` | string
`description` | string
`language` | string
`tags` | Array&lt;string&gt;
`kind` | [SnippetKind](SnippetKind.md)
`canonicalKey` | string
`id` | string
`createdAt` | Date
`updatedAt` | Date
`expiresAt` | Date
`viewCount` | number
`upvoteCount` | number
`downvoteCount` | number
`referenceCount` | number
`status` | string
`highlightedUrl` | string
`isHidden` | boolean
`hiddenReason` | string
`source` | string

## Example

```typescript
import type { SnippetMetaResponse } from '@vaddisrinivas/voltsnip-client'

// TODO: Update the object below with actual values
const example = {
  "title": null,
  "description": null,
  "language": null,
  "tags": null,
  "kind": null,
  "canonicalKey": null,
  "id": null,
  "createdAt": null,
  "updatedAt": null,
  "expiresAt": null,
  "viewCount": null,
  "upvoteCount": null,
  "downvoteCount": null,
  "referenceCount": null,
  "status": null,
  "highlightedUrl": null,
  "isHidden": null,
  "hiddenReason": null,
  "source": null,
} satisfies SnippetMetaResponse

console.log(example)

// Convert the instance to a JSON string
const exampleJSON: string = JSON.stringify(example)
console.log(exampleJSON)

// Parse the JSON string back to an object
const exampleParsed = JSON.parse(exampleJSON) as SnippetMetaResponse
console.log(exampleParsed)
```

[[Back to top]](#) [[Back to API list]](../README.md#api-endpoints) [[Back to Model list]](../README.md#models) [[Back to README]](../README.md)


