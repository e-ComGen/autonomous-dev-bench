"""Static test dependency declarations from the pre-fix tree, never inferred import names."""
import re

TEST_GROUPS = ("test", "tests", "testing", "dev")
REQUIREMENT_FILES = (
    "requirements-test.txt", "requirements_test.txt", "requirements-tests.txt", "requirements_tests.txt",
    "requirements/testing.txt", "requirements/tests.txt", "requirements/test.txt",
    "requirements-dev.txt", "requirements_dev.txt", "requirements/dev.txt",
)


def group_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ValueError("INVALID_TEST_DEPENDENCY_GROUP")
    return re.sub(r"[-_.]+", "-", name).lower()


def dependency_groups(configuration):
    groups = configuration.get("dependency-groups", {})
    if not isinstance(groups, dict):
        raise ValueError("INVALID_TEST_DEPENDENCY_GROUPS")
    normalized = {}
    for name, values in groups.items():
        key = group_name(name)
        if key in normalized:
            raise ValueError("AMBIGUOUS_TEST_DEPENDENCY_GROUP")
        normalized[key] = values
    selected = next((name for name in TEST_GROUPS if name in normalized), None)
    if selected is None:
        return None, []
    result = []

    def expand(name, stack):
        if name in stack or len(stack) >= 20:
            raise ValueError("CYCLIC_TEST_DEPENDENCY_GROUP")
        values = normalized.get(name)
        if not isinstance(values, list):
            raise ValueError("INVALID_TEST_DEPENDENCY_GROUP: " + name)
        for value in values:
            if isinstance(value, str):
                # One requirement is one argv element. No flags, control characters or shell evaluation.
                if (not re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", value)
                        or any(ord(char) < 32 for char in value) or len(value) > 4096):
                    raise ValueError("INVALID_TEST_DEPENDENCY_REQUIREMENT")
                result.append(value)
            elif isinstance(value, dict) and set(value) == {"include-group"}:
                expand(group_name(value["include-group"]), (*stack, name))
            else:
                raise ValueError("UNSUPPORTED_TEST_DEPENDENCY_GROUP_ITEM")
            if len(result) > 2048:
                raise ValueError("TEST_DEPENDENCY_GROUP_TOO_LARGE")
    expand(selected, ())
    return selected, list(dict.fromkeys(result))
