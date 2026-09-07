"""GraphQL reads; package metadata only filters candidates and does not certify a build."""
REPOSITORY_FIELDS = """
  id nameWithOwner isPrivate isFork isArchived
  primaryLanguage { name } licenseInfo { spdxId }
  projectConfig: object(expression: "HEAD:pyproject.toml") { __typename }
  setupScript: object(expression: "HEAD:setup.py") { __typename }
  setupConfig: object(expression: "HEAD:setup.cfg") { __typename }
"""
REPOSITORIES = """
query($query: String!, $cursor: String) {
  search(query: $query, type: REPOSITORY, first: 25, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on Repository { """ + REPOSITORY_FIELDS + """ } }
  }
}
"""
PULLS = """
query($query: String!, $cursor: String) {
  search(query: $query, type: ISSUE, first: 10, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      id number createdAt mergedAt merged headRefOid changedFiles
      commits(first: 1) { totalCount }
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
  repository(owner: $owner, name: $name) { """ + REPOSITORY_FIELDS + """ }
}
"""
