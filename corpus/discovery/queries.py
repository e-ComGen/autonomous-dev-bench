"""Bounded public GitHub GraphQL projections; no patch or review-body downloads."""
REPOSITORIES = """
query($query: String!, $cursor: String) {
  search(query: $query, type: REPOSITORY, first: 20, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on Repository {
      id nameWithOwner isPrivate isFork isArchived diskUsage
      licenseInfo { spdxId }
    } }
  }
}
"""
PULLS = """
query($query: String!, $cursor: String) {
  search(query: $query, type: ISSUE, first: 10, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      id number url createdAt merged headRefOid
      mergeCommit { oid parents(first: 3) { totalCount nodes { oid } } }
      closingIssuesReferences(first: 20, excludeUserLinked: true) {
        pageInfo { hasNextPage }
        nodes { number repository { nameWithOwner isPrivate } }
      }
    } }
  }
}
"""
ISSUE = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    isPrivate
    issue(number: $number) { id number url title body createdAt lastEditedAt }
  }
}
"""
