"""Project quotas count distinct qualified projects, not downloaded repositories."""
from collections import Counter


class Selection:
    def __init__(self, policy, requested):
        self.policy, self.requested = policy, requested
        self.selected = []
        self.projects = {}
        self.per_project = Counter()

    def deficits(self):
        counts = Counter(self.projects.values())
        return {name: max(0, getattr(self.policy, name + "_projects") - counts[name])
                for name in ("small", "medium", "large")}

    def wants(self, project, scale):
        if self.per_project[project] >= self.policy.tasks_per_project:
            return False
        deficits = self.deficits()
        left = self.requested - len(self.selected)
        if left <= 0:
            return False
        if project not in self.projects and deficits[scale]:
            return True
        return left > sum(deficits.values())

    def add(self, task, prepared):
        project = task.project_id
        scale = prepared["captured"]["classification"]["scale"]
        if not self.wants(project, scale):
            return False
        self.projects[project] = scale
        self.per_project[project] += 1
        self.selected.append((task, prepared))
        return True

    @property
    def complete(self):
        return len(self.selected) == self.requested and not any(self.deficits().values())
