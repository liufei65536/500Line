"""有向图，用于表示任务之间的依赖关系"""

from collections import defaultdict

class Graph:
    """使用有向图构建任务之间的关系。
    任务通过可哈希值标识，并且（该可哈希值）可作为Python字典的键。
    """
    sort_key = None

    def __init__(self):
        self._inputs_of = defaultdict(set)
        self._consequences_of = defaultdict(set)

    def sorted(self, nodes, reverse=False):
        """对节点进行排序。
        """
        nodes = list(nodes)  # grab nodes in one pass, in case it's a generator
        try:
            nodes.sort(key=self.sort_key, reverse=reverse)
        except TypeError:
            pass
        return nodes

    def add_edge(self, input_task, consequence_task):
        """添加边: `consequence_task` 是`input_task`的后续"""
        self._consequences_of[input_task].add(consequence_task)
        self._inputs_of[consequence_task].add(input_task)

    def remove_edge(self, input_task, consequence_task):
        """移除边"""
        self._consequences_of[input_task].remove(consequence_task)
        self._inputs_of[consequence_task].remove(input_task)

    def inputs_of(self, task):
        """`task`的输入"""
        return self.sorted(self._inputs_of[task])

    def clear_inputs_of(self, task):
        """移除所有指向`task`的边"""
        input_tasks = self._inputs_of.pop(task, ())
        for input_task in input_tasks:
            self._consequences_of[input_task].remove(task)

    def tasks(self):
        """Return all task identifiers."""
        return self.sorted(set(self._inputs_of).union(self._consequences_of))

    def edges(self):
        """Return all edges as ``(input_task, consequence_task)`` tuples."""
        return [(a, b) for a in self.sorted(self._consequences_of)
                       for b in self.sorted(self._consequences_of[a])]

    def immediate_consequences_of(self, task):
        """返回 `task` 指向的节点"""
        return self.sorted(self._consequences_of[task])

    def recursive_consequences_of(self, tasks, include=False):
        """返回给定 `tasks` 的拓扑排序后果。

        返回一个有序列表，其中包含通过从给定 `tasks` 沿着后续边向下到使用它们作为输入的任务的所有可达任务。
        这将返回一个可行的任务执行顺序。
        （返回列表的顺序选择使得所有后果的输入在列表中都出现在后果之前。这意味着如果按给定顺序逐一执行列表中的任务，
        这些任务应该会发现它们需要的输入（或至少是它们上次需要的输入）已经计算完毕并可用。）
        `include`： 若为真，则 `tasks` 本身将被正确排序到结果序列中。否则，它们将被省略。
        """
        def visit(task):
            visited.add(task)
            consequences = self._consequences_of[task]
            for consequence in self.sorted(consequences, reverse=True):
                if consequence not in visited:
                    yield from visit(consequence)
                    yield consequence

        def generate_consequences_backwards():
            for task in self.sorted(tasks, reverse=True):
                yield from visit(task)
                if include:
                    yield task

        visited = set()
        return list(generate_consequences_backwards())[::-1]
