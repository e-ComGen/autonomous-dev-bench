"""Narrow GraphQL reads; issue text is never used as host instructions."""
REPOSITORIES = """
query($query: String!, $cursor: String) {
  search(query: $query, type: REPOSITORY, first: 25, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on Repository {
      id nameWithOwner isPrivate isFork isArchived
      primaryLanguage { name } licenseInfo { spdxId }
    } }
  }
}
"""
PULLS = """
query($query: String!, $cursor: String) {
  search(query: $query, type: ISSUE, first: 10, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      id number createdAt mergedAt merged headRefOid changedFiles
      commits { totalCount }
      mergeCommit { oid parents(first: 3) { totalCount nodes { oid } } }
      closingIssuesReferences(first: 6, excludeUserLinked: true) {
        pageInfo { hasNextPage }
        nodes { id number title body createdAt lastEditedAt
                repository { nameWithOwner isPrivate } }
      }
    } }
  }
}
"""
REPO = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    id nameWithOwner isPrivate isFork isArchived
    primaryLanguage { name } licenseInfo { spdxId }
  }
}
"""
