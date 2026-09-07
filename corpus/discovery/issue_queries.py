"""Bounded GraphQL metadata; paths aid rejection, never replace source/test qualification."""
REPOSITORY_FIELDS = """
  id nameWithOwner isPrivate isFork isArchived
  primaryLanguage { name } licenseInfo { spdxId }
  projectConfig: object(expression: "HEAD:pyproject.toml") { __typename }
  setupScript: object(expression: "HEAD:setup.py") { __typename }
  setupConfig: object(expression: "HEAD:setup.cfg") { __typename }
  testsTree: object(expression: "HEAD:tests") { __typename }
  testTree: object(expression: "HEAD:test") { __typename }
  testingTree: object(expression: "HEAD:testing") { __typename }
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
      files(first: 31) { totalCount pageInfo { hasNextPage } nodes { path changeType } }
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
