"""Bounded repository sampling across star bands; no fixed project/task fallback."""


def repository_searches(policy):
    # Star bands diversify discovery, not project-size or quality classifications.
    bands = ((0, 999), (1000, 9999), (10000, policy.max_stars))
    ranges = [(max(low, policy.min_stars), min(high, policy.max_stars))
              for low, high in bands if max(low, policy.min_stars) <= min(high, policy.max_stars)]
    if not ranges:
        return []
    quotient, remainder = divmod(policy.repository_pool, len(ranges))
    result = []
    for index, (low, high) in enumerate(ranges):
        limit = quotient + (index < remainder)
        if not limit:
            continue
        order = "updated-desc" if low >= 10000 else "stars-desc"
        query = (f"language:Python is:public fork:false archived:false stars:{low}..{high} "
                 f"pushed:>={policy.since} sort:{order}")
        result.append((query, limit))
    return result


def has_test_tree(repository):
    # A HEAD hint only orders candidates. Absence never rejects nested/historical tests.
    return any((repository.get(name) or {}).get("__typename") == "Tree"
               for name in ("testsTree", "testTree", "testingTree"))
